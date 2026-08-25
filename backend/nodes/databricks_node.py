"""
Databricks workspace automation node.

Full-coverage integration with the Databricks Workspace REST API (387 operations
across ~35 service groups):
- Compute: Clusters (full lifecycle + events/node-types/spark-versions), Cluster
  Policies (+compliance), Instance Pools, Instance Profiles, Libraries, Global
  Init Scripts, Command Execution (1.2), Policy Families
- Workflows: Jobs 2.2 (create/run/update/reset/repair/export/compliance) + runs
- SQL: Statement Execution, Warehouses (+workspace config), Queries, Query
  History, Visualizations, Alerts
- Unity Catalog: Catalogs, Schemas, Tables, Volumes, Functions, Registered
  Models + Versions, External Locations, Storage Credentials, Connections,
  Metastores, Grants/permissions, System Schemas, Artifact Allowlists, Resource
  Quotas, Constraints, Quality Monitors, Online Tables, Lineage
- Files: Workspace objects, Repos, Git Credentials, DBFS, Files API (UC volumes)
- Secrets: scopes, secrets, ACLs
- Pipelines (Delta Live Tables)
- ML: Serving Endpoints, Vector Search (endpoints + indexes), MLflow Experiments
  + Runs, MLflow Model Registry + Model Registry Webhooks, Feature Store
- Identity & Access: SCIM (Users/Groups/Service Principals/Me), Permissions,
  Permission Assignments, Tokens, Token Management, IP Access Lists, Workspace Conf
- Delivery: Apps, Lakeview Dashboards, Genie
- Webhook Triggers: one trigger per job-notification event (on start / success /
  failure / duration-warning / any) — a passive receiver filtered by event_type

Authentication: Personal Access Token, sent as `Authorization: Bearer <token>`.
The workspace host is per-account/per-cloud, so the credential also carries the
workspace instance URL. (Databricks OAuth apps are account-scoped, not global —
unlike Google/Slack there is no single shared app that works across customer
accounts — so only PAT is exposed; service-principal auth is a manual paste.)

API Base URL: https://<workspace-instance>/  (versions are per-resource: SQL/
Workspace/Secrets = 2.0, Clusters/Unity Catalog = 2.1, Jobs = 2.2)
Documentation: https://docs.databricks.com/api/workspace/introduction
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import SSRFError, guarded_async_client

logger = logging.getLogger(__name__)


def _normalize_host(workspace_url: str) -> str:
    """Return a bare scheme+host with no trailing slash or path."""
    raw = (workspace_url or "").strip()
    if not raw:
        raise SSRFError("A Databricks workspace URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = httpx.URL(raw)
    except (TypeError, ValueError) as error:
        raise SSRFError("Databricks workspace URL is invalid") from error
    port = parsed.port or (443 if parsed.scheme == "https" else None)
    if (
        parsed.scheme != "https"
        or not parsed.host
        or parsed.username
        or parsed.password
        or port != 443
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SSRFError(
            "Databricks workspace URL must be one HTTPS host without credentials, "
            "a port, path, query, or fragment"
        )
    return f"https://{parsed.host.lower().rstrip('.')}"


# ============================================================================
# Credential Schema
# ============================================================================


class DatabricksTokenCredential(BaseModel):
    """Personal Access Token credential for Databricks (workspace-scoped)."""

    credential_type: Literal["databricks_token"] = Field(
        "databricks_token", json_schema_extra={"ui:hidden": True}
    )
    workspace_url: str = Field(
        ...,
        title="Workspace URL",
        description="Your Databricks workspace host, e.g. https://dbc-a1b2345c-d6e7.cloud.databricks.com",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="A Databricks personal access token (User Settings -> Developer -> Access tokens)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://docs.databricks.com/aws/en/dev-tools/auth/pat",
            "x-credential-instructions": (
                "Generate a personal access token under User Settings -> Developer -> "
                "Access tokens in your Databricks workspace, then paste your workspace "
                "URL and the token here."
            ),
        }
    )


DatabricksCredential = DatabricksTokenCredential


# ============================================================================
# Operation Configs
# ============================================================================


class DatabricksRunStatementConfig(BaseModel):
    """Execute a SQL statement on a SQL warehouse."""

    operation: Literal["run_statement"] = Field(
        "run_statement",
        json_schema_extra={
            "const": "run_statement",
            "ui:hidden": True,
            "x-category": "SQL",
            "x-is-trigger": False,
            "x-display-name": "Run SQL Statement",
        },
        title="Run SQL Statement",
    )
    warehouse_id: str = Field(
        ...,
        title="SQL Warehouse",
        description="The SQL warehouse to run the statement on",
        json_schema_extra={
            "x-resource-type": "databricks_warehouse",
            "x-dynamic-options": {
                "field_name": "warehouse_id",
                "placeholder": "Select a SQL warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a warehouse ID",
            }
        },
    )
    statement: str = Field(
        ...,
        title="SQL Statement",
        description="The SQL text to execute",
        json_schema_extra={"ui:widget": "textarea"},
    )
    catalog: Optional[str] = Field(
        None, title="Catalog", description="Unity Catalog catalog to run against (optional)"
    )
    db_schema: Optional[str] = Field(
        None,
        title="Schema",
        description="Schema to run against (optional)",
    )
    wait_timeout: Optional[str] = Field(
        "30s",
        title="Wait Timeout",
        description="How long to wait inline before returning a statement_id (0s or 5s-50s)",
    )
    on_wait_timeout: Optional[str] = Field(
        "CONTINUE",
        title="On Wait Timeout",
        description="What to do if the wait timeout elapses",
        json_schema_extra={
            "enum": ["CONTINUE", "CANCEL"],
            "enumNames": ["Continue asynchronously", "Cancel"],
            "x-enum-searchable": True,
        },
    )


class DatabricksGetStatementConfig(BaseModel):
    """Poll status and fetch results for a SQL statement."""

    operation: Literal["get_statement"] = Field(
        "get_statement",
        json_schema_extra={
            "const": "get_statement",
            "ui:hidden": True,
            "x-category": "SQL",
            "x-is-trigger": False,
            "x-display-name": "Get SQL Statement",
        },
        title="Get SQL Statement",
    )
    statement_id: str = Field(
        ..., title="Statement ID", description="The statement_id returned by Run SQL Statement"
    )


class DatabricksCancelStatementConfig(BaseModel):
    """Cancel an in-progress SQL statement execution."""

    operation: Literal["cancel_statement"] = Field(
        "cancel_statement",
        json_schema_extra={
            "const": "cancel_statement",
            "ui:hidden": True,
            "x-category": "SQL",
            "x-is-trigger": False,
            "x-display-name": "Cancel SQL Statement",
        },
        title="Cancel SQL Statement",
    )
    statement_id: str = Field(
        ..., title="Statement ID", description="The statement_id to cancel"
    )


class DatabricksListWarehousesConfig(BaseModel):
    """List all SQL warehouses in the workspace."""

    operation: Literal["list_warehouses"] = Field(
        "list_warehouses",
        json_schema_extra={
            "const": "list_warehouses",
            "ui:hidden": True,
            "x-category": "SQL Warehouses",
            "x-is-trigger": False,
            "x-display-name": "List SQL Warehouses",
        },
        title="List SQL Warehouses",
    )


class DatabricksGetWarehouseConfig(BaseModel):
    """Get info/state for a single SQL warehouse."""

    operation: Literal["get_warehouse"] = Field(
        "get_warehouse",
        json_schema_extra={
            "const": "get_warehouse",
            "ui:hidden": True,
            "x-category": "SQL Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Get SQL Warehouse",
        },
        title="Get SQL Warehouse",
    )
    warehouse_id: str = Field(
        ...,
        title="SQL Warehouse",
        description="The SQL warehouse to retrieve",
        json_schema_extra={
            "x-resource-type": "databricks_warehouse",
            "x-dynamic-options": {
                "field_name": "warehouse_id",
                "placeholder": "Select a SQL warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a warehouse ID",
            }
        },
    )


class DatabricksStartWarehouseConfig(BaseModel):
    """Start (resume) a stopped SQL warehouse."""

    operation: Literal["start_warehouse"] = Field(
        "start_warehouse",
        json_schema_extra={
            "const": "start_warehouse",
            "ui:hidden": True,
            "x-category": "SQL Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Start SQL Warehouse",
        },
        title="Start SQL Warehouse",
    )
    warehouse_id: str = Field(
        ...,
        title="SQL Warehouse",
        description="The SQL warehouse to start",
        json_schema_extra={
            "x-resource-type": "databricks_warehouse",
            "x-dynamic-options": {
                "field_name": "warehouse_id",
                "placeholder": "Select a SQL warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a warehouse ID",
            }
        },
    )


class DatabricksStopWarehouseConfig(BaseModel):
    """Stop a running SQL warehouse."""

    operation: Literal["stop_warehouse"] = Field(
        "stop_warehouse",
        json_schema_extra={
            "const": "stop_warehouse",
            "ui:hidden": True,
            "x-category": "SQL Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Stop SQL Warehouse",
        },
        title="Stop SQL Warehouse",
    )
    warehouse_id: str = Field(
        ...,
        title="SQL Warehouse",
        description="The SQL warehouse to stop",
        json_schema_extra={
            "x-resource-type": "databricks_warehouse",
            "x-dynamic-options": {
                "field_name": "warehouse_id",
                "placeholder": "Select a SQL warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a warehouse ID",
            }
        },
    )


class DatabricksListJobsConfig(BaseModel):
    """List jobs in the workspace."""

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
    limit: Optional[str] = Field(
        "20", title="Limit", description="Max number of jobs to return (1-100)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


class DatabricksGetJobConfig(BaseModel):
    """Get a single job's definition."""

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
    job_id: str = Field(
        ...,
        title="Job",
        description="The job to retrieve",
        json_schema_extra={
            "x-resource-type": "databricks_job",
            "x-dynamic-options": {
                "field_name": "job_id",
                "placeholder": "Select a job...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a job ID",
            }
        },
    )


class DatabricksCreateJobConfig(BaseModel):
    """Create a new job from a JSON definition."""

    operation: Literal["create_job"] = Field(
        "create_job",
        json_schema_extra={
            "const": "create_job",
            "x-creates-resource": True,
            "x-resource-type": "databricks_job",
            "x-resource-id-path": "data.job_id",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Create Job",
        },
        title="Create Job",
    )
    name: str = Field(..., title="Job Name", description="A name for the new job")
    tasks_json: str = Field(
        ...,
        title="Tasks (JSON)",
        description="JSON array of task definitions for the job",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksRunNowConfig(BaseModel):
    """Trigger an immediate run of an existing job."""

    operation: Literal["run_now"] = Field(
        "run_now",
        json_schema_extra={
            "const": "run_now",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Run Job Now",
        },
        title="Run Job Now",
    )
    job_id: str = Field(
        ...,
        title="Job",
        description="The job to run",
        json_schema_extra={
            "x-resource-type": "databricks_job",
            "x-dynamic-options": {
                "field_name": "job_id",
                "placeholder": "Select a job...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a job ID",
            }
        },
    )
    job_parameters_json: Optional[str] = Field(
        None,
        title="Job Parameters (JSON)",
        description="Optional JSON object of job parameters to override",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksSubmitRunConfig(BaseModel):
    """Submit a one-time run without creating a persistent job."""

    operation: Literal["submit_run"] = Field(
        "submit_run",
        json_schema_extra={
            "const": "submit_run",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Submit One-Time Run",
        },
        title="Submit One-Time Run",
    )
    run_name: Optional[str] = Field(
        None, title="Run Name", description="An optional name for the one-time run"
    )
    tasks_json: str = Field(
        ...,
        title="Tasks (JSON)",
        description="JSON array of task definitions for the one-time run",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksListRunsConfig(BaseModel):
    """List job runs, filterable by job."""

    operation: Literal["list_runs"] = Field(
        "list_runs",
        json_schema_extra={
            "const": "list_runs",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "List Job Runs",
        },
        title="List Job Runs",
    )
    job_id: Optional[str] = Field(
        None,
        title="Job",
        description="Filter runs to this job (optional)",
        json_schema_extra={
            "x-resource-type": "databricks_job",
            "x-dynamic-options": {
                "field_name": "job_id",
                "placeholder": "Select a job...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a job ID",
            }
        },
    )
    active_only: Optional[str] = Field(
        "false",
        title="Active Only",
        description="Only return active runs",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of runs to return (1-25)"
    )


class DatabricksGetRunConfig(BaseModel):
    """Get details/state of a single run."""

    operation: Literal["get_run"] = Field(
        "get_run",
        json_schema_extra={
            "const": "get_run",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Get Job Run",
        },
        title="Get Job Run",
    )
    run_id: str = Field(..., title="Run ID", description="The run to retrieve")


class DatabricksGetRunOutputConfig(BaseModel):
    """Retrieve the output of a completed task run."""

    operation: Literal["get_run_output"] = Field(
        "get_run_output",
        json_schema_extra={
            "const": "get_run_output",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Get Run Output",
        },
        title="Get Run Output",
    )
    run_id: str = Field(
        ..., title="Run ID", description="The task run whose output to retrieve"
    )


class DatabricksCancelRunConfig(BaseModel):
    """Cancel an active run."""

    operation: Literal["cancel_run"] = Field(
        "cancel_run",
        json_schema_extra={
            "const": "cancel_run",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Cancel Job Run",
        },
        title="Cancel Job Run",
    )
    run_id: str = Field(..., title="Run ID", description="The run to cancel")


class DatabricksDeleteJobConfig(BaseModel):
    """Delete a job."""

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
    job_id: str = Field(
        ...,
        title="Job",
        description="The job to delete",
        json_schema_extra={
            "x-resource-type": "databricks_job",
            "x-dynamic-options": {
                "field_name": "job_id",
                "placeholder": "Select a job...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a job ID",
            }
        },
    )


class DatabricksListClustersConfig(BaseModel):
    """List all clusters in the workspace."""

    operation: Literal["list_clusters"] = Field(
        "list_clusters",
        json_schema_extra={
            "const": "list_clusters",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "List Clusters",
        },
        title="List Clusters",
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


class DatabricksGetClusterConfig(BaseModel):
    """Get info/state for one cluster."""

    operation: Literal["get_cluster"] = Field(
        "get_cluster",
        json_schema_extra={
            "const": "get_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Get Cluster",
        },
        title="Get Cluster",
    )
    cluster_id: str = Field(
        ...,
        title="Cluster",
        description="The cluster to retrieve",
        json_schema_extra={
            "x-resource-type": "databricks_cluster",
            "x-dynamic-options": {
                "field_name": "cluster_id",
                "placeholder": "Select a cluster...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a cluster ID",
            }
        },
    )


class DatabricksCreateClusterConfig(BaseModel):
    """Create and start a new compute cluster."""

    operation: Literal["create_cluster"] = Field(
        "create_cluster",
        json_schema_extra={
            "const": "create_cluster",
            "x-creates-resource": True,
            "x-resource-type": "databricks_cluster",
            "x-resource-id-path": "data.cluster_id",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Create Cluster",
        },
        title="Create Cluster",
    )
    cluster_name: str = Field(..., title="Cluster Name", description="A name for the new cluster")
    spark_version: str = Field(
        ..., title="Spark Version", description="The runtime/Spark version key (e.g. 13.3.x-scala2.12)"
    )
    node_type_id: str = Field(
        ..., title="Node Type ID", description="The cloud instance type for worker nodes"
    )
    num_workers: Optional[str] = Field(
        "1", title="Number of Workers", description="Number of worker nodes"
    )


class DatabricksStartClusterConfig(BaseModel):
    """Start a terminated cluster."""

    operation: Literal["start_cluster"] = Field(
        "start_cluster",
        json_schema_extra={
            "const": "start_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Start Cluster",
        },
        title="Start Cluster",
    )
    cluster_id: str = Field(
        ...,
        title="Cluster",
        description="The cluster to start",
        json_schema_extra={
            "x-resource-type": "databricks_cluster",
            "x-dynamic-options": {
                "field_name": "cluster_id",
                "placeholder": "Select a cluster...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a cluster ID",
            }
        },
    )


class DatabricksTerminateClusterConfig(BaseModel):
    """Terminate (stop) a cluster."""

    operation: Literal["terminate_cluster"] = Field(
        "terminate_cluster",
        json_schema_extra={
            "const": "terminate_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Terminate Cluster",
        },
        title="Terminate Cluster",
    )
    cluster_id: str = Field(
        ...,
        title="Cluster",
        description="The cluster to terminate",
        json_schema_extra={
            "x-resource-type": "databricks_cluster",
            "x-dynamic-options": {
                "field_name": "cluster_id",
                "placeholder": "Select a cluster...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a cluster ID",
            }
        },
    )


class DatabricksListCatalogsConfig(BaseModel):
    """List Unity Catalog catalogs."""

    operation: Literal["list_catalogs"] = Field(
        "list_catalogs",
        json_schema_extra={
            "const": "list_catalogs",
            "ui:hidden": True,
            "x-category": "Unity Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Catalogs",
        },
        title="List Catalogs",
    )


class DatabricksListSchemasConfig(BaseModel):
    """List schemas in a catalog."""

    operation: Literal["list_schemas"] = Field(
        "list_schemas",
        json_schema_extra={
            "const": "list_schemas",
            "ui:hidden": True,
            "x-category": "Unity Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Schemas",
        },
        title="List Schemas",
    )
    catalog_name: str = Field(
        ...,
        title="Catalog",
        description="The catalog whose schemas to list",
        json_schema_extra={
            "x-resource-type": "databricks_catalog",
            "x-dynamic-options": {
                "field_name": "catalog_name",
                "placeholder": "Select a catalog...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a catalog name",
            }
        },
    )


class DatabricksListTablesConfig(BaseModel):
    """List tables in a schema."""

    operation: Literal["list_tables"] = Field(
        "list_tables",
        json_schema_extra={
            "const": "list_tables",
            "ui:hidden": True,
            "x-category": "Unity Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Tables",
        },
        title="List Tables",
    )
    catalog_name: str = Field(
        ...,
        title="Catalog",
        description="The catalog containing the schema",
        json_schema_extra={
            "x-resource-type": "databricks_catalog",
            "x-dynamic-options": {
                "field_name": "catalog_name",
                "placeholder": "Select a catalog...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a catalog name",
            }
        },
    )
    schema_name: str = Field(
        ..., title="Schema", description="The schema whose tables to list"
    )


class DatabricksGetTableConfig(BaseModel):
    """Get a table's metadata/columns by full name."""

    operation: Literal["get_table"] = Field(
        "get_table",
        json_schema_extra={
            "const": "get_table",
            "ui:hidden": True,
            "x-category": "Unity Catalog",
            "x-is-trigger": False,
            "x-display-name": "Get Table",
        },
        title="Get Table",
    )
    full_name: str = Field(
        ...,
        title="Table Full Name",
        description="Three-level name catalog.schema.table",
    )


class DatabricksListWorkspaceConfig(BaseModel):
    """List notebooks/folders/files under a workspace path."""

    operation: Literal["list_workspace"] = Field(
        "list_workspace",
        json_schema_extra={
            "const": "list_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Objects",
        },
        title="List Workspace Objects",
    )
    path: str = Field(
        ..., title="Path", description="The workspace path to list (e.g. /Users/me)"
    )


class DatabricksExportWorkspaceConfig(BaseModel):
    """Export a notebook/file."""

    operation: Literal["export_workspace"] = Field(
        "export_workspace",
        json_schema_extra={
            "const": "export_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Export Workspace Object",
        },
        title="Export Workspace Object",
    )
    path: str = Field(
        ..., title="Path", description="The workspace path of the object to export"
    )
    export_format: Optional[str] = Field(
        "SOURCE",
        title="Format",
        description="Export format",
        json_schema_extra={
            "enum": ["SOURCE", "HTML", "JUPYTER", "DBC"],
            "enumNames": ["Source", "HTML", "Jupyter", "DBC"],
            "x-enum-searchable": True,
        },
    )


class DatabricksImportWorkspaceConfig(BaseModel):
    """Import a notebook/file to a workspace path."""

    operation: Literal["import_workspace"] = Field(
        "import_workspace",
        json_schema_extra={
            "const": "import_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Import Workspace Object",
        },
        title="Import Workspace Object",
    )
    path: str = Field(
        ..., title="Path", description="The destination workspace path"
    )
    content: str = Field(
        ...,
        title="Content (base64)",
        description="Base64-encoded content of the object to import",
        json_schema_extra={"ui:widget": "textarea"},
    )
    import_format: Optional[str] = Field(
        "SOURCE",
        title="Format",
        description="Import format",
        json_schema_extra={
            "enum": ["SOURCE", "HTML", "JUPYTER", "DBC", "AUTO"],
            "enumNames": ["Source", "HTML", "Jupyter", "DBC", "Auto"],
            "x-enum-searchable": True,
        },
    )
    language: Optional[str] = Field(
        "PYTHON",
        title="Language",
        description="Notebook language (required for SOURCE format)",
        json_schema_extra={
            "enum": ["PYTHON", "SCALA", "SQL", "R"],
            "enumNames": ["Python", "Scala", "SQL", "R"],
            "x-enum-searchable": True,
        },
    )
    overwrite: Optional[str] = Field(
        "false",
        title="Overwrite",
        description="Overwrite an existing object at the path",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DatabricksListSecretScopesConfig(BaseModel):
    """List secret scopes."""

    operation: Literal["list_secret_scopes"] = Field(
        "list_secret_scopes",
        json_schema_extra={
            "const": "list_secret_scopes",
            "ui:hidden": True,
            "x-category": "Secrets",
            "x-is-trigger": False,
            "x-display-name": "List Secret Scopes",
        },
        title="List Secret Scopes",
    )


# ============================================================================
# Webhook Trigger Config (receiver — Databricks has no registerable webhook API)
# ============================================================================

# Databricks job webhook notification event types. The job notification
# destination POSTs a JSON payload whose `event_type` field is one of these.
# Docs: https://docs.databricks.com/aws/en/jobs/notifications
DATABRICKS_WEBHOOK_EVENT_TYPES = [
    "jobs.on_start",
    "jobs.on_success",
    "jobs.on_failure",
    "jobs.on_duration_warning_threshold_exceeded",
]

# One trigger operation per job-notification event. Databricks has no
# registerable webhook API: the user pastes the provisioned URL into a job's
# webhook notification destination, and every attached event POSTs to the same
# URL, so each trigger filters deliveries at runtime by the payload's
# `event_type`. The "*" sentinel (On Any Job Event) passes every event.
# (operation, event_type, display, description)
DATABRICKS_TRIGGER_SPECS = [
    ("on_job_start", "jobs.on_start", "On Job Run Started",
     "Fires when a Databricks job run starts."),
    ("on_job_success", "jobs.on_success", "On Job Run Succeeded",
     "Fires when a Databricks job run completes successfully."),
    ("on_job_failure", "jobs.on_failure", "On Job Run Failed",
     "Fires when a Databricks job run ends in an unsuccessful state."),
    ("on_job_duration_warning", "jobs.on_duration_warning_threshold_exceeded",
     "On Job Duration Threshold Exceeded",
     "Fires when a Databricks job run exceeds its configured duration warning threshold."),
    ("on_any_job_event", "*", "On Any Job Event",
     "Fires on any Databricks job webhook notification event."),
]
# op -> the Databricks event_type it filters ("*" = every event).
DATABRICKS_TRIGGER_EVENT = {op: ev for op, ev, _, _ in DATABRICKS_TRIGGER_SPECS}


class _DatabricksWebhookTrigger(BaseModel):
    """Base for Databricks per-event webhook triggers. Databricks has no
    registerable webhook API — the user pastes the provisioned URL into a job's
    webhook notification destination; each concrete trigger filters deliveries
    by the payload's `event_type` (see filter_trigger_payload)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as a notification destination in your Databricks workspace and attach it to a job's webhook notifications.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


def _make_databricks_trigger(operation: str, display: str, description: str) -> type:
    return create_model(
        f"Databricks{''.join(p.capitalize() for p in operation.split('_'))}Config",
        __base__=_DatabricksWebhookTrigger,
        __doc__=description,
        operation=(
            Literal[operation],
            Field(
                operation,
                title=display,
                description=description,
                json_schema_extra={
                    "const": operation,
                    "ui:hidden": True,
                    "x-category": "Triggers",
                    "x-is-trigger": True,
                    "x-display-name": display,
                },
            ),
        ),
    )


# op -> concrete trigger config class (one operation per job event).
DATABRICKS_TRIGGER_CONFIGS = {
    op: _make_databricks_trigger(op, display, desc)
    for op, ev, display, desc in DATABRICKS_TRIGGER_SPECS
}


# ============================================================================
# Operation registry (populated by the generated per-service blocks below)
# ============================================================================


# Inline "Create new <resource>" builder affordances.
_FIELD_RESOURCE_TYPE: Dict[str, str] = {
    "warehouse_id": "databricks_warehouse",
    "job_id": "databricks_job",
    "cluster_id": "databricks_cluster",
    "catalog_name": "databricks_catalog",
}


def _dyn(field_name: str, label: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    """Build an x-dynamic-options block (searchable dropdown + custom paste)."""
    opts: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": f"Select {label}...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": f"Or paste a {label}",
    }
    if depends_on:
        opts["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": opts}
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


# Per-service blocks below append their config classes here and their
# op_name -> async handler(c, host, token) into OPERATION_HANDLERS.
OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}


# ============================================================================
# <<DATABRICKS_GENERATED_BLOCKS>>
# ============================================================================


# ---- Clusters (12 ops) ----
class DatabricksEditClusterConfig(BaseModel):
    """Update the configuration of an existing all-purpose cluster."""
    operation: Literal["edit_cluster"] = Field(
        "edit_cluster",
        json_schema_extra={"const": "edit_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Edit Cluster"},
        title="Edit Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to edit.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    spec_json: str = Field(
        "{}", title="Cluster Spec (JSON)",
        description="Full cluster spec (spark_version, node_type_id, num_workers, autoscale, etc.). cluster_id is merged in automatically.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _edit_cluster(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.spec_json, "Cluster Spec") or {}
    body["cluster_id"] = c.cluster_id
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/edit", json_body=body, action_name="edit_cluster")


class DatabricksResizeClusterConfig(BaseModel):
    """Resize a cluster to a target number of workers or autoscale range."""
    operation: Literal["resize_cluster"] = Field(
        "resize_cluster",
        json_schema_extra={"const": "resize_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Resize Cluster"},
        title="Resize Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to resize.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    num_workers: Optional[str] = Field(
        None, title="Number of Workers",
        description="Fixed number of worker nodes. Leave empty to use autoscale instead.",
    )
    autoscale_json: str = Field(
        "{}", title="Autoscale (JSON)",
        description="Autoscale spec, e.g. {\"min_workers\": 2, \"max_workers\": 8}. Used when num_workers is empty.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _resize_cluster(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {"cluster_id": c.cluster_id}
    if c.num_workers not in (None, ""):
        body["num_workers"] = int(c.num_workers)
    autoscale = _parse_json_field(c.autoscale_json, "Autoscale")
    if autoscale:
        body["autoscale"] = autoscale
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/resize", json_body=body, action_name="resize_cluster")


class DatabricksRestartClusterConfig(BaseModel):
    """Restart a running cluster."""
    operation: Literal["restart_cluster"] = Field(
        "restart_cluster",
        json_schema_extra={"const": "restart_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Restart Cluster"},
        title="Restart Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to restart.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    restart_time: Optional[str] = Field(
        None, title="Restart Time (epoch ms)",
        description="Optional timestamp (epoch milliseconds) at which the restart occurred.",
    )


async def _restart_cluster(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {"cluster_id": c.cluster_id}
    if c.restart_time not in (None, ""):
        body["restart_time"] = int(c.restart_time)
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/restart", json_body=body, action_name="restart_cluster")


class DatabricksPinClusterConfig(BaseModel):
    """Pin a cluster so it stays in the cluster list after termination."""
    operation: Literal["pin_cluster"] = Field(
        "pin_cluster",
        json_schema_extra={"const": "pin_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Pin Cluster"},
        title="Pin Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to pin.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )


async def _pin_cluster(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/pin", json_body={"cluster_id": c.cluster_id}, action_name="pin_cluster")


class DatabricksUnpinClusterConfig(BaseModel):
    """Unpin a cluster so it can be removed from the list after termination."""
    operation: Literal["unpin_cluster"] = Field(
        "unpin_cluster",
        json_schema_extra={"const": "unpin_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Unpin Cluster"},
        title="Unpin Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to unpin.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )


async def _unpin_cluster(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/unpin", json_body={"cluster_id": c.cluster_id}, action_name="unpin_cluster")


class DatabricksPermanentDeleteClusterConfig(BaseModel):
    """Permanently delete a cluster, removing it from the cluster list."""
    operation: Literal["permanent_delete_cluster"] = Field(
        "permanent_delete_cluster",
        json_schema_extra={"const": "permanent_delete_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Permanently Delete Cluster"},
        title="Permanently Delete Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to permanently delete.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )


async def _permanent_delete_cluster(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/permanent-delete", json_body={"cluster_id": c.cluster_id}, action_name="permanent_delete_cluster")


class DatabricksChangeClusterOwnerConfig(BaseModel):
    """Change the owner of a cluster."""
    operation: Literal["change_cluster_owner"] = Field(
        "change_cluster_owner",
        json_schema_extra={"const": "change_cluster_owner", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Change Cluster Owner"},
        title="Change Cluster Owner",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster whose owner will change.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    owner_username: str = Field(
        ..., title="New Owner Username",
        description="Email/username of the new cluster owner.",
    )


async def _change_cluster_owner(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/change-owner", json_body={"cluster_id": c.cluster_id, "owner_username": c.owner_username}, action_name="change_cluster_owner")


class DatabricksGetClusterEventsConfig(BaseModel):
    """Retrieve the event log for a cluster."""
    operation: Literal["get_cluster_events"] = Field(
        "get_cluster_events",
        json_schema_extra={"const": "get_cluster_events", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Get Cluster Events"},
        title="Get Cluster Events",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to fetch events for.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    limit: Optional[str] = Field(
        None, title="Limit",
        description="Maximum number of events to return per page (default 50, max 500).",
    )
    order: Optional[str] = Field(
        None, title="Order",
        description="Order to list events in.",
        json_schema_extra={"enum": ["ASC", "DESC"], "enumNames": ["Ascending", "Descending"], "x-enum-searchable": True},
    )
    start_time: Optional[str] = Field(
        None, title="Start Time (epoch ms)",
        description="Start time in epoch milliseconds. Events after this time are returned.",
    )
    end_time: Optional[str] = Field(
        None, title="End Time (epoch ms)",
        description="End time in epoch milliseconds. Events before this time are returned.",
    )
    event_types_json: str = Field(
        "[]", title="Event Types (JSON)",
        description="Optional list of event types to filter by, e.g. [\"RUNNING\", \"TERMINATING\"].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _get_cluster_events(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {"cluster_id": c.cluster_id, "order": c.order}
    if c.limit not in (None, ""):
        body["limit"] = int(c.limit)
    if c.start_time not in (None, ""):
        body["start_time"] = int(c.start_time)
    if c.end_time not in (None, ""):
        body["end_time"] = int(c.end_time)
    event_types = _parse_json_field(c.event_types_json, "Event Types")
    if event_types:
        body["event_types"] = event_types
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/events", json_body=body, action_name="get_cluster_events")


class DatabricksUpdateClusterConfig(BaseModel):
    """Partially update a cluster's configuration using a field mask."""
    operation: Literal["update_cluster"] = Field(
        "update_cluster",
        json_schema_extra={"const": "update_cluster", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "Update Cluster"},
        title="Update Cluster",
    )
    cluster_id: str = Field(
        ..., title="Cluster",
        description="ID of the cluster to update.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    update_mask: str = Field(
        ..., title="Update Mask",
        description="Comma-separated field mask of the cluster fields to update, e.g. \"num_workers,autoscale\".",
    )
    cluster_json: str = Field(
        "{}", title="Cluster (JSON)",
        description="Partial cluster spec containing the fields named in the update mask.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_cluster(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {"cluster_id": c.cluster_id, "update_mask": c.update_mask}
    cluster = _parse_json_field(c.cluster_json, "Cluster")
    if cluster:
        body["cluster"] = cluster
    return await _databricks_request(host, token, "POST", "/api/2.1/clusters/update", json_body=body, action_name="update_cluster")


class DatabricksListNodeTypesConfig(BaseModel):
    """List supported Spark node (instance) types."""
    operation: Literal["list_node_types"] = Field(
        "list_node_types",
        json_schema_extra={"const": "list_node_types", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "List Node Types"},
        title="List Node Types",
    )


async def _list_node_types(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/clusters/list-node-types", action_name="list_node_types")


class DatabricksListAvailabilityZonesConfig(BaseModel):
    """List the availability zones where clusters can be created."""
    operation: Literal["list_availability_zones"] = Field(
        "list_availability_zones",
        json_schema_extra={"const": "list_availability_zones", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "List Availability Zones"},
        title="List Availability Zones",
    )


async def _list_availability_zones(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/clusters/list-zones", action_name="list_availability_zones")


class DatabricksListSparkVersionsConfig(BaseModel):
    """List the Spark/Databricks Runtime versions available for clusters."""
    operation: Literal["list_spark_versions"] = Field(
        "list_spark_versions",
        json_schema_extra={"const": "list_spark_versions", "ui:hidden": True,
                           "x-category": "Clusters", "x-is-trigger": False,
                           "x-display-name": "List Spark Versions"},
        title="List Spark Versions",
    )


async def _list_spark_versions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/clusters/spark-versions", action_name="list_spark_versions")


OPERATION_CONFIGS.extend([
    DatabricksEditClusterConfig,
    DatabricksResizeClusterConfig,
    DatabricksRestartClusterConfig,
    DatabricksPinClusterConfig,
    DatabricksUnpinClusterConfig,
    DatabricksPermanentDeleteClusterConfig,
    DatabricksChangeClusterOwnerConfig,
    DatabricksGetClusterEventsConfig,
    DatabricksUpdateClusterConfig,
    DatabricksListNodeTypesConfig,
    DatabricksListAvailabilityZonesConfig,
    DatabricksListSparkVersionsConfig,
])
OPERATION_HANDLERS.update({
    "edit_cluster": _edit_cluster,
    "resize_cluster": _resize_cluster,
    "restart_cluster": _restart_cluster,
    "pin_cluster": _pin_cluster,
    "unpin_cluster": _unpin_cluster,
    "permanent_delete_cluster": _permanent_delete_cluster,
    "change_cluster_owner": _change_cluster_owner,
    "get_cluster_events": _get_cluster_events,
    "update_cluster": _update_cluster,
    "list_node_types": _list_node_types,
    "list_availability_zones": _list_availability_zones,
    "list_spark_versions": _list_spark_versions,
})


# ---- Cluster Policies (10 ops) ----
class DatabricksListClusterPoliciesConfig(BaseModel):
    """List all cluster policies in the workspace."""

    operation: Literal["list_cluster_policies"] = Field(
        "list_cluster_policies",
        json_schema_extra={
            "const": "list_cluster_policies",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "List Cluster Policies",
        },
        title="List Cluster Policies",
    )
    sort_column: Optional[str] = Field(
        None,
        title="Sort Column",
        description="Column to sort the returned policies by",
        json_schema_extra={
            "enum": ["SORT_BY_POLICY_NAME", "SORT_BY_CREATION_TIME"],
            "enumNames": ["Policy Name", "Creation Time"],
            "x-enum-searchable": True,
        },
    )
    sort_order: Optional[str] = Field(
        None,
        title="Sort Order",
        description="Order in which the policies are sorted",
        json_schema_extra={
            "enum": ["ASC", "DESC"],
            "enumNames": ["Ascending", "Descending"],
            "x-enum-searchable": True,
        },
    )


class DatabricksGetClusterPolicyConfig(BaseModel):
    """Get a single cluster policy by its ID."""

    operation: Literal["get_cluster_policy"] = Field(
        "get_cluster_policy",
        json_schema_extra={
            "const": "get_cluster_policy",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Get Cluster Policy",
        },
        title="Get Cluster Policy",
    )
    policy_id: str = Field(
        ..., title="Policy ID", description="The ID of the cluster policy to retrieve"
    )


class DatabricksCreateClusterPolicyConfig(BaseModel):
    """Create a new cluster policy from a policy definition."""

    operation: Literal["create_cluster_policy"] = Field(
        "create_cluster_policy",
        json_schema_extra={
            "const": "create_cluster_policy",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Create Cluster Policy",
        },
        title="Create Cluster Policy",
    )
    name: str = Field(
        ..., title="Policy Name", description="A short, human-readable name for the policy"
    )
    definition_json: str = Field(
        "{}",
        title="Policy Definition (JSON)",
        description="Policy definition document expressed in the Databricks Cluster Policy Definition Language",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    description: Optional[str] = Field(
        None, title="Description", description="Additional human-readable description of the policy"
    )
    policy_family_id: Optional[str] = Field(
        None,
        title="Policy Family ID",
        description="ID of a policy family to base this policy on (definition is used as overrides)",
    )
    max_clusters_per_user: Optional[int] = Field(
        None,
        title="Max Clusters Per User",
        description="Max number of clusters per user that can be active using this policy",
    )


class DatabricksEditClusterPolicyConfig(BaseModel):
    """Update an existing cluster policy's name and definition."""

    operation: Literal["edit_cluster_policy"] = Field(
        "edit_cluster_policy",
        json_schema_extra={
            "const": "edit_cluster_policy",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Edit Cluster Policy",
        },
        title="Edit Cluster Policy",
    )
    policy_id: str = Field(
        ..., title="Policy ID", description="The ID of the cluster policy to update"
    )
    name: str = Field(
        ..., title="Policy Name", description="A short, human-readable name for the policy"
    )
    definition_json: str = Field(
        "{}",
        title="Policy Definition (JSON)",
        description="Policy definition document expressed in the Databricks Cluster Policy Definition Language",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeleteClusterPolicyConfig(BaseModel):
    """Delete a cluster policy by its ID."""

    operation: Literal["delete_cluster_policy"] = Field(
        "delete_cluster_policy",
        json_schema_extra={
            "const": "delete_cluster_policy",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Delete Cluster Policy",
        },
        title="Delete Cluster Policy",
    )
    policy_id: str = Field(
        ..., title="Policy ID", description="The ID of the cluster policy to delete"
    )


class DatabricksListClusterPolicyComplianceConfig(BaseModel):
    """List the compliance status of all clusters governed by a policy."""

    operation: Literal["list_cluster_policy_compliance"] = Field(
        "list_cluster_policy_compliance",
        json_schema_extra={
            "const": "list_cluster_policy_compliance",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "List Policy Compliance",
        },
        title="List Policy Compliance",
    )
    policy_id: str = Field(
        ..., title="Policy ID", description="The ID of the cluster policy to check compliance for"
    )


class DatabricksGetClusterPolicyComplianceConfig(BaseModel):
    """Get the compliance status of a single cluster against its policy."""

    operation: Literal["get_cluster_policy_compliance"] = Field(
        "get_cluster_policy_compliance",
        json_schema_extra={
            "const": "get_cluster_policy_compliance",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Get Cluster Compliance",
        },
        title="Get Cluster Compliance",
    )
    policy_id: str = Field(
        ..., title="Policy ID", description="The ID of the cluster policy"
    )
    cluster_id: str = Field(
        ...,
        title="Cluster",
        description="The cluster whose compliance status is checked",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )


class DatabricksEnforceClusterPolicyComplianceConfig(BaseModel):
    """Update a cluster to bring it into compliance with its assigned policy."""

    operation: Literal["enforce_cluster_policy_compliance"] = Field(
        "enforce_cluster_policy_compliance",
        json_schema_extra={
            "const": "enforce_cluster_policy_compliance",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Enforce Cluster Compliance",
        },
        title="Enforce Cluster Compliance",
    )
    cluster_id: str = Field(
        ...,
        title="Cluster",
        description="The cluster to bring into policy compliance",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    validate_only: str = Field(
        "false",
        title="Validate Only",
        description="If enabled, only show the changes that would be made without applying them",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DatabricksListPolicyFamiliesConfig(BaseModel):
    """List all available cluster policy families."""

    operation: Literal["list_policy_families"] = Field(
        "list_policy_families",
        json_schema_extra={
            "const": "list_policy_families",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "List Policy Families",
        },
        title="List Policy Families",
    )
    max_results: Optional[int] = Field(
        None,
        title="Max Results",
        description="Maximum number of policy families to return per page",
    )
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="A token from a previous response used to fetch the next page",
    )


class DatabricksGetPolicyFamilyConfig(BaseModel):
    """Get a single cluster policy family by its ID."""

    operation: Literal["get_policy_family"] = Field(
        "get_policy_family",
        json_schema_extra={
            "const": "get_policy_family",
            "ui:hidden": True,
            "x-category": "Cluster Policies",
            "x-is-trigger": False,
            "x-display-name": "Get Policy Family",
        },
        title="Get Policy Family",
    )
    policy_family_id: str = Field(
        ..., title="Policy Family ID", description="The ID of the policy family to retrieve"
    )
    version: Optional[int] = Field(
        None,
        title="Version",
        description="The version number of the policy family to retrieve",
    )


async def _list_cluster_policies(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        "/api/2.0/policies/clusters/list",
        params={"sort_column": c.sort_column, "sort_order": c.sort_order},
        action_name="list_cluster_policies",
    )


async def _get_cluster_policy(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        "/api/2.0/policies/clusters/get",
        params={"policy_id": c.policy_id},
        action_name="get_cluster_policy",
    )


async def _create_cluster_policy(c, host, token) -> Dict[str, Any]:
    definition = _parse_json_field(c.definition_json, "Policy Definition")
    return await _databricks_request(
        host,
        token,
        "POST",
        "/api/2.0/policies/clusters/create",
        json_body={
            "name": c.name,
            "definition": definition,
            "description": c.description,
            "policy_family_id": c.policy_family_id,
            "max_clusters_per_user": c.max_clusters_per_user,
        },
        action_name="create_cluster_policy",
    )


async def _edit_cluster_policy(c, host, token) -> Dict[str, Any]:
    definition = _parse_json_field(c.definition_json, "Policy Definition")
    return await _databricks_request(
        host,
        token,
        "POST",
        "/api/2.0/policies/clusters/edit",
        json_body={
            "policy_id": c.policy_id,
            "name": c.name,
            "definition": definition,
        },
        action_name="edit_cluster_policy",
    )


async def _delete_cluster_policy(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "POST",
        "/api/2.0/policies/clusters/delete",
        json_body={"policy_id": c.policy_id},
        action_name="delete_cluster_policy",
    )


async def _list_cluster_policy_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        "/api/2.0/policies/clusters/list-compliance",
        params={"policy_id": c.policy_id},
        action_name="list_cluster_policy_compliance",
    )


async def _get_cluster_policy_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        "/api/2.0/policies/clusters/get-compliance",
        params={"policy_id": c.policy_id, "cluster_id": c.cluster_id},
        action_name="get_cluster_policy_compliance",
    )


async def _enforce_cluster_policy_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "POST",
        "/api/2.0/policies/clusters/enforce-compliance",
        json_body={
            "cluster_id": c.cluster_id,
            "validate_only": c.validate_only == "true",
        },
        action_name="enforce_cluster_policy_compliance",
    )


async def _list_policy_families(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        "/api/2.0/policy-families",
        params={"max_results": c.max_results, "page_token": c.page_token},
        action_name="list_policy_families",
    )


async def _get_policy_family(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host,
        token,
        "GET",
        f"/api/2.0/policy-families/{c.policy_family_id}",
        params={"version": c.version},
        action_name="get_policy_family",
    )


OPERATION_CONFIGS.extend([
    DatabricksListClusterPoliciesConfig,
    DatabricksGetClusterPolicyConfig,
    DatabricksCreateClusterPolicyConfig,
    DatabricksEditClusterPolicyConfig,
    DatabricksDeleteClusterPolicyConfig,
    DatabricksListClusterPolicyComplianceConfig,
    DatabricksGetClusterPolicyComplianceConfig,
    DatabricksEnforceClusterPolicyComplianceConfig,
    DatabricksListPolicyFamiliesConfig,
    DatabricksGetPolicyFamilyConfig,
])
OPERATION_HANDLERS.update({
    "list_cluster_policies": _list_cluster_policies,
    "get_cluster_policy": _get_cluster_policy,
    "create_cluster_policy": _create_cluster_policy,
    "edit_cluster_policy": _edit_cluster_policy,
    "delete_cluster_policy": _delete_cluster_policy,
    "list_cluster_policy_compliance": _list_cluster_policy_compliance,
    "get_cluster_policy_compliance": _get_cluster_policy_compliance,
    "enforce_cluster_policy_compliance": _enforce_cluster_policy_compliance,
    "list_policy_families": _list_policy_families,
    "get_policy_family": _get_policy_family,
})


# ---- Instance Pools (9 ops) ----
class DatabricksListInstancePoolsConfig(BaseModel):
    """List all instance pools in the workspace."""
    operation: Literal["list_instance_pools"] = Field(
        "list_instance_pools",
        json_schema_extra={"const": "list_instance_pools", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "List Instance Pools"},
        title="List Instance Pools",
    )


async def _list_instance_pools(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/instance-pools/list", action_name="list_instance_pools")


class DatabricksGetInstancePoolConfig(BaseModel):
    """Retrieve the configuration of a single instance pool."""
    operation: Literal["get_instance_pool"] = Field(
        "get_instance_pool",
        json_schema_extra={"const": "get_instance_pool", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Get Instance Pool"},
        title="Get Instance Pool",
    )
    instance_pool_id: str = Field(..., title="Instance Pool ID", description="The canonical unique identifier for the instance pool.")


async def _get_instance_pool(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/instance-pools/get", params={"instance_pool_id": c.instance_pool_id}, action_name="get_instance_pool")


class DatabricksCreateInstancePoolConfig(BaseModel):
    """Create a new instance pool."""
    operation: Literal["create_instance_pool"] = Field(
        "create_instance_pool",
        json_schema_extra={"const": "create_instance_pool", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Create Instance Pool"},
        title="Create Instance Pool",
    )
    instance_pool_name: str = Field(..., title="Instance Pool Name", description="A human-readable name for the instance pool.")
    node_type_id: str = Field(..., title="Node Type ID", description="The node type of instances the pool provides (e.g. i3.xlarge).")
    pool_json: str = Field("{}", title="Pool Spec (JSON)", description="Full instance pool spec merged into the request body (min_idle_instances, max_capacity, idle_instance_autotermination_minutes, aws_attributes, custom_tags, preloaded_spark_versions, etc.).",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_instance_pool(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.pool_json, "Pool Spec") or {}
    body["instance_pool_name"] = c.instance_pool_name
    body["node_type_id"] = c.node_type_id
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-pools/create", json_body=body, action_name="create_instance_pool")


class DatabricksEditInstancePoolConfig(BaseModel):
    """Edit an existing instance pool. All required fields must be supplied."""
    operation: Literal["edit_instance_pool"] = Field(
        "edit_instance_pool",
        json_schema_extra={"const": "edit_instance_pool", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Edit Instance Pool"},
        title="Edit Instance Pool",
    )
    instance_pool_id: str = Field(..., title="Instance Pool ID", description="The canonical unique identifier for the instance pool to edit.")
    instance_pool_name: str = Field(..., title="Instance Pool Name", description="A human-readable name for the instance pool.")
    node_type_id: str = Field(..., title="Node Type ID", description="The node type of instances the pool provides (e.g. i3.xlarge).")
    pool_json: str = Field("{}", title="Pool Spec (JSON)", description="Full instance pool spec merged into the request body (min_idle_instances, max_capacity, idle_instance_autotermination_minutes, custom_tags, etc.).",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _edit_instance_pool(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.pool_json, "Pool Spec") or {}
    body["instance_pool_id"] = c.instance_pool_id
    body["instance_pool_name"] = c.instance_pool_name
    body["node_type_id"] = c.node_type_id
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-pools/edit", json_body=body, action_name="edit_instance_pool")


class DatabricksDeleteInstancePoolConfig(BaseModel):
    """Delete an instance pool, terminating its idle instances asynchronously."""
    operation: Literal["delete_instance_pool"] = Field(
        "delete_instance_pool",
        json_schema_extra={"const": "delete_instance_pool", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Delete Instance Pool"},
        title="Delete Instance Pool",
    )
    instance_pool_id: str = Field(..., title="Instance Pool ID", description="The canonical unique identifier for the instance pool to delete.")


async def _delete_instance_pool(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-pools/delete", json_body={"instance_pool_id": c.instance_pool_id}, action_name="delete_instance_pool")


class DatabricksListInstanceProfilesConfig(BaseModel):
    """List the instance profiles that the calling user can use to launch clusters."""
    operation: Literal["list_instance_profiles"] = Field(
        "list_instance_profiles",
        json_schema_extra={"const": "list_instance_profiles", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "List Instance Profiles"},
        title="List Instance Profiles",
    )


async def _list_instance_profiles(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/instance-profiles/list", action_name="list_instance_profiles")


class DatabricksAddInstanceProfileConfig(BaseModel):
    """Register an instance profile so it can be used to launch clusters."""
    operation: Literal["add_instance_profile"] = Field(
        "add_instance_profile",
        json_schema_extra={"const": "add_instance_profile", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Add Instance Profile"},
        title="Add Instance Profile",
    )
    instance_profile_arn: str = Field(..., title="Instance Profile ARN", description="The AWS ARN of the instance profile to register.")
    iam_role_arn: Optional[str] = Field(None, title="IAM Role ARN", description="The AWS IAM role ARN of the role associated with the instance profile (for meta instance profiles).")
    is_meta_instance_profile: str = Field("false", title="Is Meta Instance Profile", description="Whether this is a meta instance profile used for IAM credential passthrough.",
                                          json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    skip_validation: str = Field("false", title="Skip Validation", description="Skip cross-account permission validation when adding the profile.",
                                 json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _add_instance_profile(c, host, token) -> Dict[str, Any]:
    body = {
        "instance_profile_arn": c.instance_profile_arn,
        "iam_role_arn": c.iam_role_arn,
        "is_meta_instance_profile": c.is_meta_instance_profile == "true",
        "skip_validation": c.skip_validation == "true",
    }
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-profiles/add", json_body=body, action_name="add_instance_profile")


class DatabricksEditInstanceProfileConfig(BaseModel):
    """Edit the IAM role association of a registered instance profile."""
    operation: Literal["edit_instance_profile"] = Field(
        "edit_instance_profile",
        json_schema_extra={"const": "edit_instance_profile", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Edit Instance Profile"},
        title="Edit Instance Profile",
    )
    instance_profile_arn: str = Field(..., title="Instance Profile ARN", description="The AWS ARN of the instance profile to edit.")
    iam_role_arn: Optional[str] = Field(None, title="IAM Role ARN", description="The AWS IAM role ARN of the role associated with the instance profile.")


async def _edit_instance_profile(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-profiles/edit", json_body={"instance_profile_arn": c.instance_profile_arn, "iam_role_arn": c.iam_role_arn}, action_name="edit_instance_profile")


class DatabricksRemoveInstanceProfileConfig(BaseModel):
    """Remove a registered instance profile from the workspace."""
    operation: Literal["remove_instance_profile"] = Field(
        "remove_instance_profile",
        json_schema_extra={"const": "remove_instance_profile", "ui:hidden": True,
                           "x-category": "Instance Pools", "x-is-trigger": False,
                           "x-display-name": "Remove Instance Profile"},
        title="Remove Instance Profile",
    )
    instance_profile_arn: str = Field(..., title="Instance Profile ARN", description="The AWS ARN of the instance profile to remove.")


async def _remove_instance_profile(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/instance-profiles/remove", json_body={"instance_profile_arn": c.instance_profile_arn}, action_name="remove_instance_profile")


OPERATION_CONFIGS.extend([
    DatabricksListInstancePoolsConfig,
    DatabricksGetInstancePoolConfig,
    DatabricksCreateInstancePoolConfig,
    DatabricksEditInstancePoolConfig,
    DatabricksDeleteInstancePoolConfig,
    DatabricksListInstanceProfilesConfig,
    DatabricksAddInstanceProfileConfig,
    DatabricksEditInstanceProfileConfig,
    DatabricksRemoveInstanceProfileConfig,
])
OPERATION_HANDLERS.update({
    "list_instance_pools": _list_instance_pools,
    "get_instance_pool": _get_instance_pool,
    "create_instance_pool": _create_instance_pool,
    "edit_instance_pool": _edit_instance_pool,
    "delete_instance_pool": _delete_instance_pool,
    "list_instance_profiles": _list_instance_profiles,
    "add_instance_profile": _add_instance_profile,
    "edit_instance_profile": _edit_instance_profile,
    "remove_instance_profile": _remove_instance_profile,
})


# ---- Libraries (9 ops) ----
class DatabricksAllClusterLibraryStatusesConfig(BaseModel):
    """Get the status of all libraries on all clusters."""
    operation: Literal["all_cluster_library_statuses"] = Field(
        "all_cluster_library_statuses",
        json_schema_extra={"const": "all_cluster_library_statuses", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "All Cluster Library Statuses"},
        title="All Cluster Library Statuses",
    )


async def _all_cluster_library_statuses(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/libraries/all-cluster-statuses", action_name="all_cluster_library_statuses")


class DatabricksClusterLibraryStatusConfig(BaseModel):
    """Get the status of libraries on a single cluster."""
    operation: Literal["cluster_library_status"] = Field(
        "cluster_library_status",
        json_schema_extra={"const": "cluster_library_status", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Cluster Library Status"},
        title="Cluster Library Status",
    )
    cluster_id: str = Field(
        ..., title="Cluster ID", description="Unique identifier of the cluster whose library statuses to retrieve.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )


async def _cluster_library_status(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/libraries/cluster-status", params={"cluster_id": c.cluster_id}, action_name="cluster_library_status")


class DatabricksInstallLibrariesConfig(BaseModel):
    """Install libraries on a cluster."""
    operation: Literal["install_libraries"] = Field(
        "install_libraries",
        json_schema_extra={"const": "install_libraries", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Install Libraries"},
        title="Install Libraries",
    )
    cluster_id: str = Field(
        ..., title="Cluster ID", description="Unique identifier of the cluster on which to install the libraries.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    libraries_json: str = Field(
        "[]", title="Libraries (JSON)",
        description='JSON array of library objects to install, e.g. [{"pypi": {"package": "requests"}}, {"jar": "dbfs:/mnt/lib.jar"}].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _install_libraries(c, host, token) -> Dict[str, Any]:
    libraries = _parse_json_field(c.libraries_json, "Libraries") or []
    return await _databricks_request(host, token, "POST", "/api/2.0/libraries/install", json_body={"cluster_id": c.cluster_id, "libraries": libraries}, action_name="install_libraries")


class DatabricksUninstallLibrariesConfig(BaseModel):
    """Uninstall libraries from a cluster."""
    operation: Literal["uninstall_libraries"] = Field(
        "uninstall_libraries",
        json_schema_extra={"const": "uninstall_libraries", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Uninstall Libraries"},
        title="Uninstall Libraries",
    )
    cluster_id: str = Field(
        ..., title="Cluster ID", description="Unique identifier of the cluster from which to uninstall the libraries.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    libraries_json: str = Field(
        "[]", title="Libraries (JSON)",
        description='JSON array of library objects to uninstall, e.g. [{"pypi": {"package": "requests"}}].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _uninstall_libraries(c, host, token) -> Dict[str, Any]:
    libraries = _parse_json_field(c.libraries_json, "Libraries") or []
    return await _databricks_request(host, token, "POST", "/api/2.0/libraries/uninstall", json_body={"cluster_id": c.cluster_id, "libraries": libraries}, action_name="uninstall_libraries")


class DatabricksListGlobalInitScriptsConfig(BaseModel):
    """List all global init scripts in the workspace."""
    operation: Literal["list_global_init_scripts"] = Field(
        "list_global_init_scripts",
        json_schema_extra={"const": "list_global_init_scripts", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "List Global Init Scripts"},
        title="List Global Init Scripts",
    )


async def _list_global_init_scripts(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/global-init-scripts", action_name="list_global_init_scripts")


class DatabricksGetGlobalInitScriptConfig(BaseModel):
    """Get the details and content of a global init script."""
    operation: Literal["get_global_init_script"] = Field(
        "get_global_init_script",
        json_schema_extra={"const": "get_global_init_script", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Get Global Init Script"},
        title="Get Global Init Script",
    )
    script_id: str = Field(..., title="Script ID", description="Unique identifier of the global init script to retrieve.")


async def _get_global_init_script(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/global-init-scripts/{c.script_id}", action_name="get_global_init_script")


class DatabricksCreateGlobalInitScriptConfig(BaseModel):
    """Create a new global init script."""
    operation: Literal["create_global_init_script"] = Field(
        "create_global_init_script",
        json_schema_extra={"const": "create_global_init_script", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Create Global Init Script"},
        title="Create Global Init Script",
    )
    name: str = Field(..., title="Name", description="Human-readable name for the global init script.")
    script: str = Field(..., title="Script (Base64)", description="Base64-encoded content of the init script.")
    enabled: str = Field(
        "false", title="Enabled", description="Whether the script runs on all newly launched clusters.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    position: Optional[int] = Field(None, title="Position", description="Position of the script in the execution order (0-based). Lower runs first.")


async def _create_global_init_script(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/global-init-scripts", json_body={
        "name": c.name,
        "script": c.script,
        "enabled": c.enabled == "true",
        "position": c.position,
    }, action_name="create_global_init_script")


class DatabricksUpdateGlobalInitScriptConfig(BaseModel):
    """Update an existing global init script."""
    operation: Literal["update_global_init_script"] = Field(
        "update_global_init_script",
        json_schema_extra={"const": "update_global_init_script", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Update Global Init Script"},
        title="Update Global Init Script",
    )
    script_id: str = Field(..., title="Script ID", description="Unique identifier of the global init script to update.")
    name: Optional[str] = Field(None, title="Name", description="New human-readable name for the script.")
    script: Optional[str] = Field(None, title="Script (Base64)", description="New base64-encoded content of the init script.")
    enabled: Optional[str] = Field(
        None, title="Enabled", description="Whether the script runs on all newly launched clusters.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    position: Optional[int] = Field(None, title="Position", description="New position of the script in the execution order (0-based).")


async def _update_global_init_script(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/global-init-scripts/{c.script_id}", json_body={
        "name": c.name,
        "script": c.script,
        "enabled": (c.enabled == "true") if c.enabled is not None else None,
        "position": c.position,
    }, action_name="update_global_init_script")


class DatabricksDeleteGlobalInitScriptConfig(BaseModel):
    """Delete a global init script."""
    operation: Literal["delete_global_init_script"] = Field(
        "delete_global_init_script",
        json_schema_extra={"const": "delete_global_init_script", "ui:hidden": True,
                           "x-category": "Libraries", "x-is-trigger": False,
                           "x-display-name": "Delete Global Init Script"},
        title="Delete Global Init Script",
    )
    script_id: str = Field(..., title="Script ID", description="Unique identifier of the global init script to delete.")


async def _delete_global_init_script(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/global-init-scripts/{c.script_id}", action_name="delete_global_init_script")


OPERATION_CONFIGS.extend([
    DatabricksAllClusterLibraryStatusesConfig,
    DatabricksClusterLibraryStatusConfig,
    DatabricksInstallLibrariesConfig,
    DatabricksUninstallLibrariesConfig,
    DatabricksListGlobalInitScriptsConfig,
    DatabricksGetGlobalInitScriptConfig,
    DatabricksCreateGlobalInitScriptConfig,
    DatabricksUpdateGlobalInitScriptConfig,
    DatabricksDeleteGlobalInitScriptConfig,
])
OPERATION_HANDLERS.update({
    "all_cluster_library_statuses": _all_cluster_library_statuses,
    "cluster_library_status": _cluster_library_status,
    "install_libraries": _install_libraries,
    "uninstall_libraries": _uninstall_libraries,
    "list_global_init_scripts": _list_global_init_scripts,
    "get_global_init_script": _get_global_init_script,
    "create_global_init_script": _create_global_init_script,
    "update_global_init_script": _update_global_init_script,
    "delete_global_init_script": _delete_global_init_script,
})


# ---- Command Execution (6 ops) ----
class DatabricksCreateExecutionContextConfig(BaseModel):
    """Create an execution context on a cluster for running commands."""
    operation: Literal["create_execution_context"] = Field(
        "create_execution_context",
        json_schema_extra={"const": "create_execution_context", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Create Execution Context"},
        title="Create Execution Context",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster to create the execution context on.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    language: str = Field(
        "python", title="Language", description="The language for the execution context.",
        json_schema_extra={"enum": ["python", "scala", "sql", "r"],
                           "enumNames": ["Python", "Scala", "SQL", "R"],
                           "x-enum-searchable": True},
    )


async def _create_execution_context(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/1.2/contexts/create",
        json_body={"clusterId": c.cluster_id, "language": c.language},
        action_name="create_execution_context",
    )


class DatabricksGetExecutionContextStatusConfig(BaseModel):
    """Get the status of an existing execution context."""
    operation: Literal["get_execution_context_status"] = Field(
        "get_execution_context_status",
        json_schema_extra={"const": "get_execution_context_status", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Get Execution Context Status"},
        title="Get Execution Context Status",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster the context belongs to.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    context_id: str = Field(
        ..., title="Context ID", description="The ID of the execution context to check.",
    )


async def _get_execution_context_status(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/1.2/contexts/status",
        params={"clusterId": c.cluster_id, "contextId": c.context_id},
        action_name="get_execution_context_status",
    )


class DatabricksDestroyExecutionContextConfig(BaseModel):
    """Destroy an existing execution context on a cluster."""
    operation: Literal["destroy_execution_context"] = Field(
        "destroy_execution_context",
        json_schema_extra={"const": "destroy_execution_context", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Destroy Execution Context"},
        title="Destroy Execution Context",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster the context belongs to.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    context_id: str = Field(
        ..., title="Context ID", description="The ID of the execution context to destroy.",
    )


async def _destroy_execution_context(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/1.2/contexts/destroy",
        json_body={"clusterId": c.cluster_id, "contextId": c.context_id},
        action_name="destroy_execution_context",
    )


class DatabricksExecuteCommandConfig(BaseModel):
    """Run a command within an execution context on a cluster."""
    operation: Literal["execute_command"] = Field(
        "execute_command",
        json_schema_extra={"const": "execute_command", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Execute Command"},
        title="Execute Command",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster to run the command on.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    context_id: str = Field(
        ..., title="Context ID", description="The ID of the execution context to run the command in.",
    )
    language: str = Field(
        "python", title="Language", description="The language of the command.",
        json_schema_extra={"enum": ["python", "scala", "sql", "r"],
                           "enumNames": ["Python", "Scala", "SQL", "R"],
                           "x-enum-searchable": True},
    )
    command: str = Field(
        ..., title="Command", description="The command text to execute.",
    )


async def _execute_command(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/1.2/commands/execute",
        json_body={"clusterId": c.cluster_id, "contextId": c.context_id,
                   "language": c.language, "command": c.command},
        action_name="execute_command",
    )


class DatabricksGetCommandStatusConfig(BaseModel):
    """Get the status and result of a command execution."""
    operation: Literal["get_command_status"] = Field(
        "get_command_status",
        json_schema_extra={"const": "get_command_status", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Get Command Status"},
        title="Get Command Status",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster the command ran on.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    context_id: str = Field(
        ..., title="Context ID", description="The ID of the execution context the command ran in.",
    )
    command_id: str = Field(
        ..., title="Command ID", description="The ID of the command to check.",
    )


async def _get_command_status(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/1.2/commands/status",
        params={"clusterId": c.cluster_id, "contextId": c.context_id, "commandId": c.command_id},
        action_name="get_command_status",
    )


class DatabricksCancelCommandConfig(BaseModel):
    """Cancel a running command in an execution context."""
    operation: Literal["cancel_command"] = Field(
        "cancel_command",
        json_schema_extra={"const": "cancel_command", "ui:hidden": True,
                           "x-category": "Command Execution", "x-is-trigger": False,
                           "x-display-name": "Cancel Command"},
        title="Cancel Command",
    )
    cluster_id: str = Field(
        ..., title="Cluster", description="The ID of the cluster the command is running on.",
        json_schema_extra=_dyn("cluster_id", "a cluster"),
    )
    context_id: str = Field(
        ..., title="Context ID", description="The ID of the execution context the command is running in.",
    )
    command_id: str = Field(
        ..., title="Command ID", description="The ID of the command to cancel.",
    )


async def _cancel_command(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/1.2/commands/cancel",
        json_body={"clusterId": c.cluster_id, "contextId": c.context_id, "commandId": c.command_id},
        action_name="cancel_command",
    )


OPERATION_CONFIGS.extend([
    DatabricksCreateExecutionContextConfig,
    DatabricksGetExecutionContextStatusConfig,
    DatabricksDestroyExecutionContextConfig,
    DatabricksExecuteCommandConfig,
    DatabricksGetCommandStatusConfig,
    DatabricksCancelCommandConfig,
])
OPERATION_HANDLERS.update({
    "create_execution_context": _create_execution_context,
    "get_execution_context_status": _get_execution_context_status,
    "destroy_execution_context": _destroy_execution_context,
    "execute_command": _execute_command,
    "get_command_status": _get_command_status,
    "cancel_command": _cancel_command,
})


# ---- Jobs (9 ops) ----
class DatabricksUpdateJobConfig(BaseModel):
    """Add, update, or remove specific settings of an existing job."""
    operation: Literal["update_job"] = Field(
        "update_job",
        json_schema_extra={"const": "update_job", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Update Job"},
        title="Update Job",
    )
    job_id: str = Field(..., title="Job ID", description="The canonical identifier of the job to update.",
                        json_schema_extra=_dyn("job_id", "a job"))
    new_settings_json: str = Field("{}", title="New Settings (JSON)",
        description="The new settings for the job. Fields provided are added/updated; use Fields to Remove to delete top-level fields.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    fields_to_remove_json: str = Field("[]", title="Fields to Remove (JSON)",
        description="JSON array of top-level field names to remove from the job settings (e.g. [\"schedule\", \"libraries\"]).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class DatabricksResetJobConfig(BaseModel):
    """Overwrite all settings for a given job with the provided settings."""
    operation: Literal["reset_job"] = Field(
        "reset_job",
        json_schema_extra={"const": "reset_job", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Reset Job"},
        title="Reset Job",
    )
    job_id: str = Field(..., title="Job ID", description="The canonical identifier of the job to reset.",
                        json_schema_extra=_dyn("job_id", "a job"))
    new_settings_json: str = Field("{}", title="New Settings (JSON)",
        description="The complete new settings of the job. All existing settings are replaced entirely.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class DatabricksRepairRunConfig(BaseModel):
    """Re-run one or more tasks of a failed job run."""
    operation: Literal["repair_run"] = Field(
        "repair_run",
        json_schema_extra={"const": "repair_run", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Repair Run"},
        title="Repair Run",
    )
    run_id: str = Field(..., title="Run ID", description="The job run ID of the run to repair. The run must not be in progress.")
    repair_json: str = Field("{}", title="Repair Options (JSON)",
        description="Repair options object: rerun_tasks (array of task keys), latest_repair_id, rerun_all_failed_tasks (bool), job_parameters, notebook_params, etc.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class DatabricksCancelAllRunsConfig(BaseModel):
    """Cancel all active runs of a job."""
    operation: Literal["cancel_all_runs"] = Field(
        "cancel_all_runs",
        json_schema_extra={"const": "cancel_all_runs", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Cancel All Runs"},
        title="Cancel All Runs",
    )
    job_id: Optional[str] = Field(None, title="Job ID",
        description="The canonical identifier of the job to cancel all runs of. Optional if All Queued Runs is set.",
        json_schema_extra=_dyn("job_id", "a job"))
    all_queued_runs: str = Field("false", title="All Queued Runs",
        description="Cancel all queued runs across all jobs in the workspace. If set, Job ID must not be provided.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


class DatabricksDeleteRunConfig(BaseModel):
    """Delete a non-active run. Returns an error if the run is active."""
    operation: Literal["delete_run"] = Field(
        "delete_run",
        json_schema_extra={"const": "delete_run", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Delete Run"},
        title="Delete Run",
    )
    run_id: str = Field(..., title="Run ID", description="The canonical identifier of the run to delete.")


class DatabricksExportRunConfig(BaseModel):
    """Export and retrieve the job run task rendered notebook output."""
    operation: Literal["export_run"] = Field(
        "export_run",
        json_schema_extra={"const": "export_run", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Export Run"},
        title="Export Run",
    )
    run_id: str = Field(..., title="Run ID", description="The canonical identifier for the run to export.")
    views_to_export: Optional[str] = Field(None, title="Views to Export",
        description="Which views to export.",
        json_schema_extra={"enum": ["CODE", "DASHBOARDS", "ALL"],
                           "enumNames": ["Code", "Dashboards", "All"], "x-enum-searchable": True})


class DatabricksListJobComplianceConfig(BaseModel):
    """List the compliance status of all jobs using a given policy."""
    operation: Literal["list_job_compliance"] = Field(
        "list_job_compliance",
        json_schema_extra={"const": "list_job_compliance", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "List Job Compliance"},
        title="List Job Compliance",
    )
    policy_id: str = Field(..., title="Policy ID", description="Canonical unique identifier for the cluster policy.")
    page_token: Optional[str] = Field(None, title="Page Token", description="A page token that can be used to navigate to the next page or previous page.")


class DatabricksGetJobComplianceConfig(BaseModel):
    """Get the compliance status of a job, including whether it is in violation of its policy."""
    operation: Literal["get_job_compliance"] = Field(
        "get_job_compliance",
        json_schema_extra={"const": "get_job_compliance", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Get Job Compliance"},
        title="Get Job Compliance",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the job whose compliance status you are requesting.",
                        json_schema_extra=_dyn("job_id", "a job"))


class DatabricksEnforceJobComplianceConfig(BaseModel):
    """Update a job so its cluster requirements conform to the current policy."""
    operation: Literal["enforce_job_compliance"] = Field(
        "enforce_job_compliance",
        json_schema_extra={"const": "enforce_job_compliance", "ui:hidden": True,
                           "x-category": "Jobs", "x-is-trigger": False,
                           "x-display-name": "Enforce Job Compliance"},
        title="Enforce Job Compliance",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the job to enforce policy compliance on.",
                        json_schema_extra=_dyn("job_id", "a job"))
    validate_only: str = Field("false", title="Validate Only",
        description="If set, previews the changes that would be made without actually enforcing them.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _update_job(c, host, token) -> Dict[str, Any]:
    body = {"job_id": int(c.job_id),
            "new_settings": _parse_json_field(c.new_settings_json, "New Settings") or {}}
    fields = _parse_json_field(c.fields_to_remove_json, "Fields to Remove")
    if fields:
        body["fields_to_remove"] = fields
    return await _databricks_request(host, token, "POST", "/api/2.2/jobs/update", json_body=body, action_name="update_job")


async def _reset_job(c, host, token) -> Dict[str, Any]:
    body = {"job_id": int(c.job_id),
            "new_settings": _parse_json_field(c.new_settings_json, "New Settings") or {}}
    return await _databricks_request(host, token, "POST", "/api/2.2/jobs/reset", json_body=body, action_name="reset_job")


async def _repair_run(c, host, token) -> Dict[str, Any]:
    body = {"run_id": int(c.run_id)}
    body.update(_parse_json_field(c.repair_json, "Repair Options") or {})
    return await _databricks_request(host, token, "POST", "/api/2.2/jobs/runs/repair", json_body=body, action_name="repair_run")


async def _cancel_all_runs(c, host, token) -> Dict[str, Any]:
    body = {
        "job_id": int(c.job_id) if c.job_id else None,
        "all_queued_runs": c.all_queued_runs == "true",
    }
    return await _databricks_request(host, token, "POST", "/api/2.2/jobs/runs/cancel-all", json_body=body, action_name="cancel_all_runs")


async def _delete_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.2/jobs/runs/delete", json_body={"run_id": int(c.run_id)}, action_name="delete_run")


async def _export_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.2/jobs/runs/export",
                                     params={"run_id": c.run_id, "views_to_export": c.views_to_export},
                                     action_name="export_run")


async def _list_job_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.2/policies/jobs/list-compliance",
                                     params={"policy_id": c.policy_id, "page_token": c.page_token},
                                     action_name="list_job_compliance")


async def _get_job_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.2/policies/jobs/get-compliance",
                                     params={"job_id": c.job_id}, action_name="get_job_compliance")


async def _enforce_job_compliance(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.2/policies/jobs/enforce-compliance",
                                     json_body={"job_id": int(c.job_id), "validate_only": c.validate_only == "true"},
                                     action_name="enforce_job_compliance")


OPERATION_CONFIGS.extend([
    DatabricksUpdateJobConfig,
    DatabricksResetJobConfig,
    DatabricksRepairRunConfig,
    DatabricksCancelAllRunsConfig,
    DatabricksDeleteRunConfig,
    DatabricksExportRunConfig,
    DatabricksListJobComplianceConfig,
    DatabricksGetJobComplianceConfig,
    DatabricksEnforceJobComplianceConfig,
])
OPERATION_HANDLERS.update({
    "update_job": _update_job,
    "reset_job": _reset_job,
    "repair_run": _repair_run,
    "cancel_all_runs": _cancel_all_runs,
    "delete_run": _delete_run,
    "export_run": _export_run,
    "list_job_compliance": _list_job_compliance,
    "get_job_compliance": _get_job_compliance,
    "enforce_job_compliance": _enforce_job_compliance,
})


# ---- SQL Warehouses (5 ops) ----
class DatabricksCreateWarehouseConfig(BaseModel):
    """Create a new SQL warehouse."""
    operation: Literal["create_warehouse"] = Field(
        "create_warehouse",
        json_schema_extra={"const": "create_warehouse", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "databricks_warehouse",
            "x-resource-id-path": "data.id",
                           "x-category": "SQL Warehouses", "x-is-trigger": False,
                           "x-display-name": "Create Warehouse"},
        title="Create Warehouse",
    )
    name: str = Field(..., title="Name", description="Logical name for the SQL warehouse (must be unique).")
    cluster_size: str = Field(
        ..., title="Cluster Size",
        description="Size of the clusters allocated for this warehouse.",
        json_schema_extra={
            "enum": ["2X-Small", "X-Small", "Small", "Medium", "Large", "X-Large",
                     "2X-Large", "3X-Large", "4X-Large"],
            "enumNames": ["2X-Small", "X-Small", "Small", "Medium", "Large", "X-Large",
                          "2X-Large", "3X-Large", "4X-Large"],
            "x-enum-searchable": True,
        },
    )
    warehouse_json: str = Field(
        "{}", title="Warehouse Spec (JSON)",
        description="Full warehouse spec (e.g. min_num_clusters, max_num_clusters, auto_stop_mins, enable_serverless_compute, warehouse_type, tags, channel). Merged with name and cluster_size.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_warehouse(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.warehouse_json, "Warehouse Spec") or {}
    body["name"] = c.name
    body["cluster_size"] = c.cluster_size
    return await _databricks_request(host, token, "POST", "/api/2.0/sql/warehouses",
                                     json_body=body, action_name="create_warehouse")


class DatabricksEditWarehouseConfig(BaseModel):
    """Update the configuration of an existing SQL warehouse."""
    operation: Literal["edit_warehouse"] = Field(
        "edit_warehouse",
        json_schema_extra={"const": "edit_warehouse", "ui:hidden": True,
                           "x-category": "SQL Warehouses", "x-is-trigger": False,
                           "x-display-name": "Edit Warehouse"},
        title="Edit Warehouse",
    )
    warehouse_id: str = Field(..., title="Warehouse", description="ID of the SQL warehouse to edit.",
                              json_schema_extra=_dyn("warehouse_id", "a warehouse"))
    warehouse_json: str = Field(
        "{}", title="Warehouse Spec (JSON)",
        description="Fields to update (e.g. name, cluster_size, min_num_clusters, max_num_clusters, auto_stop_mins, warehouse_type, tags, channel, enable_serverless_compute).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _edit_warehouse(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.warehouse_json, "Warehouse Spec") or {}
    return await _databricks_request(host, token, "POST", f"/api/2.0/sql/warehouses/{c.warehouse_id}/edit",
                                     json_body=body, action_name="edit_warehouse")


class DatabricksDeleteWarehouseConfig(BaseModel):
    """Delete a SQL warehouse."""
    operation: Literal["delete_warehouse"] = Field(
        "delete_warehouse",
        json_schema_extra={"const": "delete_warehouse", "ui:hidden": True,
                           "x-category": "SQL Warehouses", "x-is-trigger": False,
                           "x-display-name": "Delete Warehouse"},
        title="Delete Warehouse",
    )
    warehouse_id: str = Field(..., title="Warehouse", description="ID of the SQL warehouse to delete.",
                              json_schema_extra=_dyn("warehouse_id", "a warehouse"))


async def _delete_warehouse(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/sql/warehouses/{c.warehouse_id}",
                                     action_name="delete_warehouse")


class DatabricksGetWarehouseWorkspaceConfigConfig(BaseModel):
    """Get the workspace-level configuration that applies to all SQL warehouses."""
    operation: Literal["get_warehouse_workspace_config"] = Field(
        "get_warehouse_workspace_config",
        json_schema_extra={"const": "get_warehouse_workspace_config", "ui:hidden": True,
                           "x-category": "SQL Warehouses", "x-is-trigger": False,
                           "x-display-name": "Get Warehouse Workspace Config"},
        title="Get Warehouse Workspace Config",
    )


async def _get_warehouse_workspace_config(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/sql/config/warehouses",
                                     action_name="get_warehouse_workspace_config")


class DatabricksSetWarehouseWorkspaceConfigConfig(BaseModel):
    """Set the workspace-level configuration that applies to all SQL warehouses."""
    operation: Literal["set_warehouse_workspace_config"] = Field(
        "set_warehouse_workspace_config",
        json_schema_extra={"const": "set_warehouse_workspace_config", "ui:hidden": True,
                           "x-category": "SQL Warehouses", "x-is-trigger": False,
                           "x-display-name": "Set Warehouse Workspace Config"},
        title="Set Warehouse Workspace Config",
    )
    config_json: str = Field(
        "{}", title="Workspace Config (JSON)",
        description="Full workspace SQL config (e.g. security_policy, data_access_config, sql_configuration_parameters, instance_profile_arn, google_service_account, enabled_warehouse_types, channel).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _set_warehouse_workspace_config(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.config_json, "Workspace Config") or {}
    return await _databricks_request(host, token, "PUT", "/api/2.0/sql/config/warehouses",
                                     json_body=body, action_name="set_warehouse_workspace_config")


OPERATION_CONFIGS.extend([
    DatabricksCreateWarehouseConfig,
    DatabricksEditWarehouseConfig,
    DatabricksDeleteWarehouseConfig,
    DatabricksGetWarehouseWorkspaceConfigConfig,
    DatabricksSetWarehouseWorkspaceConfigConfig,
])
OPERATION_HANDLERS.update({
    "create_warehouse": _create_warehouse,
    "edit_warehouse": _edit_warehouse,
    "delete_warehouse": _delete_warehouse,
    "get_warehouse_workspace_config": _get_warehouse_workspace_config,
    "set_warehouse_workspace_config": _set_warehouse_workspace_config,
})


# ---- SQL Queries (8 ops) ----
class DatabricksListQueriesConfig(BaseModel):
    """List all SQL queries in the workspace."""
    operation: Literal["list_queries"] = Field(
        "list_queries",
        json_schema_extra={"const": "list_queries", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "List Queries"},
        title="List Queries",
    )
    page_size: Optional[int] = Field(None, title="Page Size", description="Number of queries to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque token for the next page of results.")


async def _list_queries(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/sql/queries",
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_queries",
    )


class DatabricksCreateQueryConfig(BaseModel):
    """Create a new SQL query."""
    operation: Literal["create_query"] = Field(
        "create_query",
        json_schema_extra={"const": "create_query", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "Create Query"},
        title="Create Query",
    )
    display_name: str = Field(..., title="Display Name", description="The title of the query.")
    warehouse_id: str = Field(..., title="Warehouse", description="ID of the SQL warehouse attached to the query.",
                              json_schema_extra=_dyn("warehouse_id", "a warehouse"))
    query_text: str = Field(..., title="Query Text", description="The SQL text of the query.")
    query_json: str = Field(
        "{}", title="Query Object (JSON)",
        description="Full query object to merge (catalog, schema, tags, parameters, etc.). Overrides the scalar fields on conflict.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_query(c, host, token) -> Dict[str, Any]:
    query = {
        "display_name": c.display_name,
        "warehouse_id": c.warehouse_id,
        "query_text": c.query_text,
    }
    extra = _parse_json_field(c.query_json, "Query Object") or {}
    query.update(extra)
    return await _databricks_request(
        host, token, "POST", "/api/2.0/sql/queries",
        json_body={"query": query},
        action_name="create_query",
    )


class DatabricksGetQueryConfig(BaseModel):
    """Get a SQL query by ID."""
    operation: Literal["get_query"] = Field(
        "get_query",
        json_schema_extra={"const": "get_query", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "Get Query"},
        title="Get Query",
    )
    query_id: str = Field(..., title="Query ID", description="The ID of the query to fetch.")


async def _get_query(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/sql/queries/{c.query_id}",
        action_name="get_query",
    )


class DatabricksUpdateQueryConfig(BaseModel):
    """Update an existing SQL query."""
    operation: Literal["update_query"] = Field(
        "update_query",
        json_schema_extra={"const": "update_query", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "Update Query"},
        title="Update Query",
    )
    query_id: str = Field(..., title="Query ID", description="The ID of the query to update.")
    update_mask: str = Field(
        ..., title="Update Mask",
        description="Comma-separated field mask of fields to update (e.g. 'display_name,query_text').",
    )
    query_json: str = Field(
        "{}", title="Query Object (JSON)",
        description="The query object with the fields to update (display_name, query_text, warehouse_id, etc.).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_query(c, host, token) -> Dict[str, Any]:
    query = _parse_json_field(c.query_json, "Query Object") or {}
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.0/sql/queries/{c.query_id}",
        json_body={"update_mask": c.update_mask, "query": query},
        action_name="update_query",
    )


class DatabricksDeleteQueryConfig(BaseModel):
    """Move a SQL query to the trash."""
    operation: Literal["delete_query"] = Field(
        "delete_query",
        json_schema_extra={"const": "delete_query", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "Delete Query"},
        title="Delete Query",
    )
    query_id: str = Field(..., title="Query ID", description="The ID of the query to delete.")


async def _delete_query(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/sql/queries/{c.query_id}",
        action_name="delete_query",
    )


class DatabricksListQueryVisualizationsConfig(BaseModel):
    """List visualizations on a SQL query."""
    operation: Literal["list_query_visualizations"] = Field(
        "list_query_visualizations",
        json_schema_extra={"const": "list_query_visualizations", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "List Query Visualizations"},
        title="List Query Visualizations",
    )
    query_id: str = Field(..., title="Query ID", description="The ID of the query whose visualizations to list.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque token for the next page of results.")


async def _list_query_visualizations(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/sql/queries/{c.query_id}/visualizations",
        params={"page_token": c.page_token},
        action_name="list_query_visualizations",
    )


class DatabricksListQueryHistoryConfig(BaseModel):
    """List the history of SQL query executions."""
    operation: Literal["list_query_history"] = Field(
        "list_query_history",
        json_schema_extra={"const": "list_query_history", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "List Query History"},
        title="List Query History",
    )
    filter_by_json: str = Field(
        "{}", title="Filter By (JSON)",
        description="A filter object to limit results (statuses, user_ids, warehouse_ids, query_start_time_range, etc.).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    max_results: Optional[int] = Field(None, title="Max Results", description="Limit the number of results returned in one page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque token for the next page of results.")
    include_metrics: str = Field(
        "false", title="Include Metrics",
        description="Whether to include metrics about query execution.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_query_history(c, host, token) -> Dict[str, Any]:
    # Databricks query-history list is a GET whose parameters live in a JSON
    # request body (not the query string), so filter_by stays a real object.
    body = {
        "filter_by": _parse_json_field(c.filter_by_json, "Filter By"),
        "max_results": int(c.max_results) if c.max_results else None,
        "page_token": c.page_token,
        "include_metrics": True if c.include_metrics == "true" else None,
    }
    return await _databricks_request(
        host, token, "GET", "/api/2.0/sql/history/queries",
        json_body=body,
        action_name="list_query_history",
    )


class DatabricksListDataSourcesConfig(BaseModel):
    """List the SQL warehouses available as query data sources."""
    operation: Literal["list_data_sources"] = Field(
        "list_data_sources",
        json_schema_extra={"const": "list_data_sources", "ui:hidden": True,
                           "x-category": "SQL Queries", "x-is-trigger": False,
                           "x-display-name": "List Data Sources"},
        title="List Data Sources",
    )


async def _list_data_sources(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/preview/sql/data_sources",
        action_name="list_data_sources",
    )


OPERATION_CONFIGS.extend([
    DatabricksListQueriesConfig,
    DatabricksCreateQueryConfig,
    DatabricksGetQueryConfig,
    DatabricksUpdateQueryConfig,
    DatabricksDeleteQueryConfig,
    DatabricksListQueryVisualizationsConfig,
    DatabricksListQueryHistoryConfig,
    DatabricksListDataSourcesConfig,
])
OPERATION_HANDLERS.update({
    "list_queries": _list_queries,
    "create_query": _create_query,
    "get_query": _get_query,
    "update_query": _update_query,
    "delete_query": _delete_query,
    "list_query_visualizations": _list_query_visualizations,
    "list_query_history": _list_query_history,
    "list_data_sources": _list_data_sources,
})


# ---- Alerts (8 ops) ----
class DatabricksListAlertsConfig(BaseModel):
    """List alerts."""
    operation: Literal["list_alerts"] = Field(
        "list_alerts",
        json_schema_extra={"const": "list_alerts", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "List Alerts"},
        title="List Alerts",
    )
    page_size: Optional[str] = Field(None, title="Page Size", description="Number of alerts to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for the next page of results.")


async def _list_alerts(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/sql/alerts",
                                     params={"page_size": c.page_size, "page_token": c.page_token},
                                     action_name="list_alerts")


class DatabricksCreateAlertConfig(BaseModel):
    """Create an alert."""
    operation: Literal["create_alert"] = Field(
        "create_alert",
        json_schema_extra={"const": "create_alert", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Create Alert"},
        title="Create Alert",
    )
    display_name: str = Field(..., title="Display Name", description="The display name of the alert.")
    query_id: str = Field(..., title="Query ID", description="The ID of the query evaluated by the alert.")
    alert_json: str = Field("{}", title="Alert (JSON)",
                            description="Additional alert object fields (condition, custom_body, seconds_to_retrigger, etc.). Merged with display_name and query_id.",
                            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_alert(c, host, token) -> Dict[str, Any]:
    alert = _parse_json_field(c.alert_json, "Alert") or {}
    alert["display_name"] = c.display_name
    alert["query_id"] = c.query_id
    return await _databricks_request(host, token, "POST", "/api/2.0/sql/alerts",
                                     json_body={"alert": alert}, action_name="create_alert")


class DatabricksGetAlertConfig(BaseModel):
    """Get an alert."""
    operation: Literal["get_alert"] = Field(
        "get_alert",
        json_schema_extra={"const": "get_alert", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Get Alert"},
        title="Get Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The ID of the alert to retrieve.")


async def _get_alert(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/sql/alerts/{c.alert_id}",
                                     action_name="get_alert")


class DatabricksUpdateAlertConfig(BaseModel):
    """Update an alert."""
    operation: Literal["update_alert"] = Field(
        "update_alert",
        json_schema_extra={"const": "update_alert", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Update Alert"},
        title="Update Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The ID of the alert to update.")
    update_mask: str = Field(..., title="Update Mask",
                             description="Comma-separated field mask of alert fields to update (e.g. 'display_name,query_id').")
    alert_json: str = Field("{}", title="Alert (JSON)",
                            description="The alert object with fields to update.",
                            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_alert(c, host, token) -> Dict[str, Any]:
    alert = _parse_json_field(c.alert_json, "Alert") or {}
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/sql/alerts/{c.alert_id}",
                                     json_body={"update_mask": c.update_mask, "alert": alert},
                                     action_name="update_alert")


class DatabricksDeleteAlertConfig(BaseModel):
    """Delete an alert."""
    operation: Literal["delete_alert"] = Field(
        "delete_alert",
        json_schema_extra={"const": "delete_alert", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Delete Alert"},
        title="Delete Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The ID of the alert to delete.")


async def _delete_alert(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/sql/alerts/{c.alert_id}",
                                     action_name="delete_alert")


class DatabricksCreateQueryVisualizationConfig(BaseModel):
    """Create a query visualization."""
    operation: Literal["create_query_visualization"] = Field(
        "create_query_visualization",
        json_schema_extra={"const": "create_query_visualization", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Create Query Visualization"},
        title="Create Query Visualization",
    )
    visualization_json: str = Field("{}", title="Visualization (JSON)",
                                    description="The visualization object (query_id, type, serialized_query_plan, serialized_options, display_name, etc.).",
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_query_visualization(c, host, token) -> Dict[str, Any]:
    visualization = _parse_json_field(c.visualization_json, "Visualization") or {}
    return await _databricks_request(host, token, "POST", "/api/2.0/sql/visualizations",
                                     json_body={"visualization": visualization},
                                     action_name="create_query_visualization")


class DatabricksUpdateQueryVisualizationConfig(BaseModel):
    """Update a query visualization."""
    operation: Literal["update_query_visualization"] = Field(
        "update_query_visualization",
        json_schema_extra={"const": "update_query_visualization", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Update Query Visualization"},
        title="Update Query Visualization",
    )
    visualization_id: str = Field(..., title="Visualization ID", description="The ID of the visualization to update.")
    update_mask: str = Field(..., title="Update Mask",
                             description="Comma-separated field mask of visualization fields to update.")
    visualization_json: str = Field("{}", title="Visualization (JSON)",
                                    description="The visualization object with fields to update.",
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_query_visualization(c, host, token) -> Dict[str, Any]:
    visualization = _parse_json_field(c.visualization_json, "Visualization") or {}
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/sql/visualizations/{c.visualization_id}",
                                     json_body={"update_mask": c.update_mask, "visualization": visualization},
                                     action_name="update_query_visualization")


class DatabricksDeleteQueryVisualizationConfig(BaseModel):
    """Delete a query visualization."""
    operation: Literal["delete_query_visualization"] = Field(
        "delete_query_visualization",
        json_schema_extra={"const": "delete_query_visualization", "ui:hidden": True,
                           "x-category": "Alerts", "x-is-trigger": False,
                           "x-display-name": "Delete Query Visualization"},
        title="Delete Query Visualization",
    )
    visualization_id: str = Field(..., title="Visualization ID", description="The ID of the visualization to delete.")


async def _delete_query_visualization(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/sql/visualizations/{c.visualization_id}",
                                     action_name="delete_query_visualization")


OPERATION_CONFIGS.extend([
    DatabricksListAlertsConfig,
    DatabricksCreateAlertConfig,
    DatabricksGetAlertConfig,
    DatabricksUpdateAlertConfig,
    DatabricksDeleteAlertConfig,
    DatabricksCreateQueryVisualizationConfig,
    DatabricksUpdateQueryVisualizationConfig,
    DatabricksDeleteQueryVisualizationConfig,
])
OPERATION_HANDLERS.update({
    "list_alerts": _list_alerts,
    "create_alert": _create_alert,
    "get_alert": _get_alert,
    "update_alert": _update_alert,
    "delete_alert": _delete_alert,
    "create_query_visualization": _create_query_visualization,
    "update_query_visualization": _update_query_visualization,
    "delete_query_visualization": _delete_query_visualization,
})


# ---- Unity Catalog (8 ops) ----
class DatabricksCreateCatalogConfig(BaseModel):
    """Create a new catalog in Unity Catalog."""
    operation: Literal["create_catalog"] = Field(
        "create_catalog",
        json_schema_extra={"const": "create_catalog", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "databricks_catalog",
            "x-resource-id-path": "data.name",
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Catalog"},
        title="Create Catalog",
    )
    name: str = Field(..., title="Catalog Name", description="Name of the catalog to create.")
    comment: Optional[str] = Field(None, title="Comment", description="User-provided free-form text description.")
    storage_root: Optional[str] = Field(None, title="Storage Root", description="Storage root URL for managed tables within this catalog.")
    provider_name: Optional[str] = Field(None, title="Provider Name", description="Delta Sharing provider name (for a catalog created from a share).")
    share_name: Optional[str] = Field(None, title="Share Name", description="Delta Sharing share name (for a catalog created from a share).")
    properties_json: str = Field("{}", title="Properties (JSON)", description="A map of key-value properties attached to the catalog.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_catalog(c, host, token) -> Dict[str, Any]:
    body = {
        "name": c.name,
        "comment": c.comment,
        "storage_root": c.storage_root,
        "provider_name": c.provider_name,
        "share_name": c.share_name,
        "properties": _parse_json_field(c.properties_json, "Properties") or None,
    }
    return await _databricks_request(host, token, "POST", "/api/2.1/unity-catalog/catalogs", json_body=body, action_name="create_catalog")


class DatabricksGetCatalogConfig(BaseModel):
    """Get a catalog by name from Unity Catalog."""
    operation: Literal["get_catalog"] = Field(
        "get_catalog",
        json_schema_extra={"const": "get_catalog", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Catalog"},
        title="Get Catalog",
    )
    name: str = Field(..., title="Catalog Name", description="Name of the catalog to retrieve.", json_schema_extra=_dyn("catalog_name", "a catalog"))
    include_browse: str = Field("false", title="Include Browse", description="Whether to include catalogs the user only has SELECT/USE-adjacent browse access to.", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _get_catalog(c, host, token) -> Dict[str, Any]:
    params = {"include_browse": True if c.include_browse == "true" else None}
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/catalogs/{c.name}", params=params, action_name="get_catalog")


class DatabricksUpdateCatalogConfig(BaseModel):
    """Update an existing Unity Catalog catalog."""
    operation: Literal["update_catalog"] = Field(
        "update_catalog",
        json_schema_extra={"const": "update_catalog", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Catalog"},
        title="Update Catalog",
    )
    name: str = Field(..., title="Catalog Name", description="Name of the catalog to update.", json_schema_extra=_dyn("catalog_name", "a catalog"))
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the catalog.")
    comment: Optional[str] = Field(None, title="Comment", description="User-provided free-form text description.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the current owner of the catalog.")
    isolation_mode: Optional[str] = Field(None, title="Isolation Mode", description="Whether the catalog is accessible from all workspaces or a subset.", json_schema_extra={"enum": ["OPEN", "ISOLATED"], "enumNames": ["Open", "Isolated"], "x-enum-searchable": True})
    properties_json: str = Field("{}", title="Properties (JSON)", description="A map of key-value properties attached to the catalog.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_catalog(c, host, token) -> Dict[str, Any]:
    body = {
        "new_name": c.new_name,
        "comment": c.comment,
        "owner": c.owner,
        "isolation_mode": c.isolation_mode,
        "properties": _parse_json_field(c.properties_json, "Properties") or None,
    }
    return await _databricks_request(host, token, "PATCH", f"/api/2.1/unity-catalog/catalogs/{c.name}", json_body=body, action_name="update_catalog")


class DatabricksDeleteCatalogConfig(BaseModel):
    """Delete a catalog from Unity Catalog."""
    operation: Literal["delete_catalog"] = Field(
        "delete_catalog",
        json_schema_extra={"const": "delete_catalog", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Catalog"},
        title="Delete Catalog",
    )
    name: str = Field(..., title="Catalog Name", description="Name of the catalog to delete.", json_schema_extra=_dyn("catalog_name", "a catalog"))
    force: str = Field("false", title="Force", description="Force deletion even if the catalog is not empty.", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _delete_catalog(c, host, token) -> Dict[str, Any]:
    params = {"force": True if c.force == "true" else None}
    return await _databricks_request(host, token, "DELETE", f"/api/2.1/unity-catalog/catalogs/{c.name}", params=params, action_name="delete_catalog")


class DatabricksCreateSchemaConfig(BaseModel):
    """Create a new schema in a Unity Catalog catalog."""
    operation: Literal["create_schema"] = Field(
        "create_schema",
        json_schema_extra={"const": "create_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Schema"},
        title="Create Schema",
    )
    name: str = Field(..., title="Schema Name", description="Name of the schema to create.")
    catalog_name: str = Field(..., title="Catalog Name", description="Name of the parent catalog.", json_schema_extra=_dyn("catalog_name", "a catalog"))
    comment: Optional[str] = Field(None, title="Comment", description="User-provided free-form text description.")
    storage_root: Optional[str] = Field(None, title="Storage Root", description="Storage root URL for managed tables within this schema.")
    properties_json: str = Field("{}", title="Properties (JSON)", description="A map of key-value properties attached to the schema.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_schema(c, host, token) -> Dict[str, Any]:
    body = {
        "name": c.name,
        "catalog_name": c.catalog_name,
        "comment": c.comment,
        "storage_root": c.storage_root,
        "properties": _parse_json_field(c.properties_json, "Properties") or None,
    }
    return await _databricks_request(host, token, "POST", "/api/2.1/unity-catalog/schemas", json_body=body, action_name="create_schema")


class DatabricksGetSchemaConfig(BaseModel):
    """Get a schema by full name from Unity Catalog."""
    operation: Literal["get_schema"] = Field(
        "get_schema",
        json_schema_extra={"const": "get_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Schema"},
        title="Get Schema",
    )
    full_name: str = Field(..., title="Schema Full Name", description="Full three-level name of the schema (catalog.schema).")


async def _get_schema(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/schemas/{c.full_name}", action_name="get_schema")


class DatabricksUpdateSchemaConfig(BaseModel):
    """Update an existing Unity Catalog schema."""
    operation: Literal["update_schema"] = Field(
        "update_schema",
        json_schema_extra={"const": "update_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Schema"},
        title="Update Schema",
    )
    full_name: str = Field(..., title="Schema Full Name", description="Full three-level name of the schema (catalog.schema).")
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the schema.")
    comment: Optional[str] = Field(None, title="Comment", description="User-provided free-form text description.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the current owner of the schema.")
    properties_json: str = Field("{}", title="Properties (JSON)", description="A map of key-value properties attached to the schema.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_schema(c, host, token) -> Dict[str, Any]:
    body = {
        "new_name": c.new_name,
        "comment": c.comment,
        "owner": c.owner,
        "properties": _parse_json_field(c.properties_json, "Properties") or None,
    }
    return await _databricks_request(host, token, "PATCH", f"/api/2.1/unity-catalog/schemas/{c.full_name}", json_body=body, action_name="update_schema")


class DatabricksDeleteSchemaConfig(BaseModel):
    """Delete a schema from Unity Catalog."""
    operation: Literal["delete_schema"] = Field(
        "delete_schema",
        json_schema_extra={"const": "delete_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Schema"},
        title="Delete Schema",
    )
    full_name: str = Field(..., title="Schema Full Name", description="Full three-level name of the schema (catalog.schema).")
    force: str = Field("false", title="Force", description="Force deletion even if the schema is not empty.", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _delete_schema(c, host, token) -> Dict[str, Any]:
    params = {"force": True if c.force == "true" else None}
    return await _databricks_request(host, token, "DELETE", f"/api/2.1/unity-catalog/schemas/{c.full_name}", params=params, action_name="delete_schema")


OPERATION_CONFIGS.extend([
    DatabricksCreateCatalogConfig,
    DatabricksGetCatalogConfig,
    DatabricksUpdateCatalogConfig,
    DatabricksDeleteCatalogConfig,
    DatabricksCreateSchemaConfig,
    DatabricksGetSchemaConfig,
    DatabricksUpdateSchemaConfig,
    DatabricksDeleteSchemaConfig,
])
OPERATION_HANDLERS.update({
    "create_catalog": _create_catalog,
    "get_catalog": _get_catalog,
    "update_catalog": _update_catalog,
    "delete_catalog": _delete_catalog,
    "create_schema": _create_schema,
    "get_schema": _get_schema,
    "update_schema": _update_schema,
    "delete_schema": _delete_schema,
})


# ---- Unity Catalog (8 ops) ----
class DatabricksListTableSummariesConfig(BaseModel):
    """List table summaries for a catalog in Unity Catalog."""
    operation: Literal["list_table_summaries"] = Field(
        "list_table_summaries",
        json_schema_extra={"const": "list_table_summaries", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Table Summaries"},
        title="List Table Summaries",
    )
    catalog_name: str = Field(
        ..., title="Catalog", description="Name of the catalog to enumerate table summaries for.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name_pattern: Optional[str] = Field(
        None, title="Schema Name Pattern", description="SQL LIKE pattern to filter schemas (e.g. 'sales%').",
    )
    table_name_pattern: Optional[str] = Field(
        None, title="Table Name Pattern", description="SQL LIKE pattern to filter tables.",
    )
    max_results: Optional[int] = Field(
        None, title="Max Results", description="Maximum number of table summaries to return.",
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Opaque token for retrieving the next page of results.",
    )


async def _list_table_summaries(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/table-summaries",
        params={
            "catalog_name": c.catalog_name,
            "schema_name_pattern": c.schema_name_pattern,
            "table_name_pattern": c.table_name_pattern,
            "max_results": c.max_results,
            "page_token": c.page_token,
        },
        action_name="list_table_summaries",
    )


class DatabricksCheckTableExistsConfig(BaseModel):
    """Check whether a table exists in Unity Catalog."""
    operation: Literal["check_table_exists"] = Field(
        "check_table_exists",
        json_schema_extra={"const": "check_table_exists", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Check Table Exists"},
        title="Check Table Exists",
    )
    full_name: str = Field(
        ..., title="Full Table Name", description="Three-level name of the table (catalog.schema.table).",
    )


async def _check_table_exists(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/tables/{c.full_name}/exists",
        action_name="check_table_exists",
    )


class DatabricksDeleteTableConfig(BaseModel):
    """Delete a table from Unity Catalog."""
    operation: Literal["delete_table"] = Field(
        "delete_table",
        json_schema_extra={"const": "delete_table", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Table"},
        title="Delete Table",
    )
    full_name: str = Field(
        ..., title="Full Table Name", description="Three-level name of the table to delete (catalog.schema.table).",
    )


async def _delete_table(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/tables/{c.full_name}",
        action_name="delete_table",
    )


class DatabricksListVolumesConfig(BaseModel):
    """List volumes within a schema in Unity Catalog."""
    operation: Literal["list_volumes"] = Field(
        "list_volumes",
        json_schema_extra={"const": "list_volumes", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Volumes"},
        title="List Volumes",
    )
    catalog_name: str = Field(
        ..., title="Catalog", description="Name of the catalog containing the schema.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name: str = Field(
        ..., title="Schema Name", description="Name of the schema to list volumes for.",
    )
    max_results: Optional[int] = Field(
        None, title="Max Results", description="Maximum number of volumes to return.",
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Opaque token for retrieving the next page of results.",
    )


async def _list_volumes(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/volumes",
        params={
            "catalog_name": c.catalog_name,
            "schema_name": c.schema_name,
            "max_results": c.max_results,
            "page_token": c.page_token,
        },
        action_name="list_volumes",
    )


class DatabricksCreateVolumeConfig(BaseModel):
    """Create a new volume in Unity Catalog."""
    operation: Literal["create_volume"] = Field(
        "create_volume",
        json_schema_extra={"const": "create_volume", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Volume"},
        title="Create Volume",
    )
    catalog_name: str = Field(
        ..., title="Catalog", description="Name of the catalog the volume will belong to.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name: str = Field(
        ..., title="Schema Name", description="Name of the schema the volume will belong to.",
    )
    name: str = Field(
        ..., title="Volume Name", description="Name of the new volume.",
    )
    volume_type: str = Field(
        "MANAGED", title="Volume Type", description="Whether the volume is managed by Unity Catalog or external.",
        json_schema_extra={"enum": ["MANAGED", "EXTERNAL"],
                           "enumNames": ["Managed", "External"], "x-enum-searchable": True},
    )
    storage_location: Optional[str] = Field(
        None, title="Storage Location", description="Cloud storage path (required for EXTERNAL volumes).",
    )
    comment: Optional[str] = Field(
        None, title="Comment", description="Free-text description of the volume.",
    )


async def _create_volume(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/volumes",
        json_body={
            "catalog_name": c.catalog_name,
            "schema_name": c.schema_name,
            "name": c.name,
            "volume_type": c.volume_type,
            "storage_location": c.storage_location,
            "comment": c.comment,
        },
        action_name="create_volume",
    )


class DatabricksGetVolumeConfig(BaseModel):
    """Get metadata for a volume in Unity Catalog."""
    operation: Literal["get_volume"] = Field(
        "get_volume",
        json_schema_extra={"const": "get_volume", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Volume"},
        title="Get Volume",
    )
    name: str = Field(
        ..., title="Full Volume Name", description="Three-level name of the volume (catalog.schema.volume).",
    )


async def _get_volume(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/volumes/{c.name}",
        action_name="get_volume",
    )


class DatabricksUpdateVolumeConfig(BaseModel):
    """Update a volume's name, comment, or owner in Unity Catalog."""
    operation: Literal["update_volume"] = Field(
        "update_volume",
        json_schema_extra={"const": "update_volume", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Volume"},
        title="Update Volume",
    )
    name: str = Field(
        ..., title="Full Volume Name", description="Three-level name of the volume to update (catalog.schema.volume).",
    )
    new_name: Optional[str] = Field(
        None, title="New Name", description="New name for the volume.",
    )
    comment: Optional[str] = Field(
        None, title="Comment", description="Updated free-text description of the volume.",
    )
    owner: Optional[str] = Field(
        None, title="Owner", description="New owner (user or group) of the volume.",
    )


async def _update_volume(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/volumes/{c.name}",
        json_body={
            "new_name": c.new_name,
            "comment": c.comment,
            "owner": c.owner,
        },
        action_name="update_volume",
    )


class DatabricksDeleteVolumeConfig(BaseModel):
    """Delete a volume from Unity Catalog."""
    operation: Literal["delete_volume"] = Field(
        "delete_volume",
        json_schema_extra={"const": "delete_volume", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Volume"},
        title="Delete Volume",
    )
    name: str = Field(
        ..., title="Full Volume Name", description="Three-level name of the volume to delete (catalog.schema.volume).",
    )


async def _delete_volume(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/volumes/{c.name}",
        action_name="delete_volume",
    )


OPERATION_CONFIGS.extend([
    DatabricksListTableSummariesConfig,
    DatabricksCheckTableExistsConfig,
    DatabricksDeleteTableConfig,
    DatabricksListVolumesConfig,
    DatabricksCreateVolumeConfig,
    DatabricksGetVolumeConfig,
    DatabricksUpdateVolumeConfig,
    DatabricksDeleteVolumeConfig,
])
OPERATION_HANDLERS.update({
    "list_table_summaries": _list_table_summaries,
    "check_table_exists": _check_table_exists,
    "delete_table": _delete_table,
    "list_volumes": _list_volumes,
    "create_volume": _create_volume,
    "get_volume": _get_volume,
    "update_volume": _update_volume,
    "delete_volume": _delete_volume,
})


# ---- Unity Catalog (5 ops) ----
class DatabricksListFunctionsConfig(BaseModel):
    """List functions within a Unity Catalog schema."""
    operation: Literal["list_functions"] = Field(
        "list_functions",
        json_schema_extra={"const": "list_functions", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Functions"},
        title="List Functions",
    )
    catalog_name: str = Field(
        ...,
        title="Catalog Name",
        description="Name of the parent catalog for the functions.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name: str = Field(
        ...,
        title="Schema Name",
        description="Name of the parent schema for the functions.",
    )
    max_results: Optional[int] = Field(
        None,
        title="Max Results",
        description="Maximum number of functions to return per page.",
    )
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="Opaque token from a previous response to fetch the next page.",
    )


async def _list_functions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/functions",
        params={
            "catalog_name": c.catalog_name,
            "schema_name": c.schema_name,
            "max_results": c.max_results,
            "page_token": c.page_token,
        },
        action_name="list_functions",
    )


class DatabricksCreateFunctionConfig(BaseModel):
    """Create a new function in Unity Catalog."""
    operation: Literal["create_function"] = Field(
        "create_function",
        json_schema_extra={"const": "create_function", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Function"},
        title="Create Function",
    )
    function_json: str = Field(
        "{}",
        title="Function Info (JSON)",
        description="The full FunctionInfo object (name, catalog_name, schema_name, "
                    "input_params, data_type, routine_body, routine_definition, etc.).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_function(c, host, token) -> Dict[str, Any]:
    function_info = _parse_json_field(c.function_json, "Function Info") or {}
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/functions",
        json_body={"function_info": function_info},
        action_name="create_function",
    )


class DatabricksGetFunctionConfig(BaseModel):
    """Get a function from Unity Catalog by its full name."""
    operation: Literal["get_function"] = Field(
        "get_function",
        json_schema_extra={"const": "get_function", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Function"},
        title="Get Function",
    )
    name: str = Field(
        ...,
        title="Function Full Name",
        description="The three-level (fully qualified) name of the function: "
                    "catalog.schema.function.",
    )


async def _get_function(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/functions/{c.name}",
        action_name="get_function",
    )


class DatabricksUpdateFunctionConfig(BaseModel):
    """Update the owner of a Unity Catalog function."""
    operation: Literal["update_function"] = Field(
        "update_function",
        json_schema_extra={"const": "update_function", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Function"},
        title="Update Function",
    )
    name: str = Field(
        ...,
        title="Function Full Name",
        description="The three-level (fully qualified) name of the function: "
                    "catalog.schema.function.",
    )
    owner: Optional[str] = Field(
        None,
        title="Owner",
        description="Username of the new owner of the function.",
    )


async def _update_function(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/functions/{c.name}",
        json_body={"owner": c.owner},
        action_name="update_function",
    )


class DatabricksDeleteFunctionConfig(BaseModel):
    """Delete a function from Unity Catalog."""
    operation: Literal["delete_function"] = Field(
        "delete_function",
        json_schema_extra={"const": "delete_function", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Function"},
        title="Delete Function",
    )
    name: str = Field(
        ...,
        title="Function Full Name",
        description="The three-level (fully qualified) name of the function: "
                    "catalog.schema.function.",
    )
    force: str = Field(
        "false",
        title="Force Delete",
        description="Force deletion even if the function is not empty.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"],
                           "x-enum-searchable": True},
    )


async def _delete_function(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/functions/{c.name}",
        params={"force": c.force == "true"},
        action_name="delete_function",
    )


OPERATION_CONFIGS.extend([
    DatabricksListFunctionsConfig,
    DatabricksCreateFunctionConfig,
    DatabricksGetFunctionConfig,
    DatabricksUpdateFunctionConfig,
    DatabricksDeleteFunctionConfig,
])
OPERATION_HANDLERS.update({
    "list_functions": _list_functions,
    "create_function": _create_function,
    "get_function": _get_function,
    "update_function": _update_function,
    "delete_function": _delete_function,
})


# ---- Unity Catalog Models (12 ops) ----
class DatabricksListRegisteredModelsConfig(BaseModel):
    """List registered models in Unity Catalog."""
    operation: Literal["list_registered_models"] = Field(
        "list_registered_models",
        json_schema_extra={"const": "list_registered_models", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "List Registered Models"},
        title="List Registered Models",
    )
    catalog_name: Optional[str] = Field(
        None, title="Catalog", description="Filter by parent catalog name.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name: Optional[str] = Field(None, title="Schema", description="Filter by parent schema name.")
    max_results: Optional[int] = Field(None, title="Max Results", description="Maximum number of models to return.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque pagination token from a prior response.")


async def _list_registered_models(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/models",
        params={
            "catalog_name": c.catalog_name,
            "schema_name": c.schema_name,
            "max_results": c.max_results,
            "page_token": c.page_token,
        },
        action_name="list_registered_models",
    )


class DatabricksCreateRegisteredModelConfig(BaseModel):
    """Create a registered model in Unity Catalog."""
    operation: Literal["create_registered_model"] = Field(
        "create_registered_model",
        json_schema_extra={"const": "create_registered_model", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Create Registered Model"},
        title="Create Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model (unqualified).")
    catalog_name: str = Field(
        ..., title="Catalog", description="Parent catalog name.",
        json_schema_extra=_dyn("catalog_name", "a catalog"),
    )
    schema_name: str = Field(..., title="Schema", description="Parent schema name.")
    comment: Optional[str] = Field(None, title="Comment", description="User-supplied free-form text.")
    storage_location: Optional[str] = Field(None, title="Storage Location", description="The storage location on the cloud under which model version data files are stored.")


async def _create_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/models",
        json_body={
            "name": c.name,
            "catalog_name": c.catalog_name,
            "schema_name": c.schema_name,
            "comment": c.comment,
            "storage_location": c.storage_location,
        },
        action_name="create_registered_model",
    )


class DatabricksGetRegisteredModelConfig(BaseModel):
    """Get a registered model by its full three-level name."""
    operation: Literal["get_registered_model"] = Field(
        "get_registered_model",
        json_schema_extra={"const": "get_registered_model", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Get Registered Model"},
        title="Get Registered Model",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    include_aliases: str = Field(
        "false", title="Include Aliases", description="Whether to include aliases associated with the model.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _get_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/models/{c.full_name}",
        params={"include_aliases": c.include_aliases == "true"},
        action_name="get_registered_model",
    )


class DatabricksUpdateRegisteredModelConfig(BaseModel):
    """Update a registered model's name, comment, or owner."""
    operation: Literal["update_registered_model"] = Field(
        "update_registered_model",
        json_schema_extra={"const": "update_registered_model", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Update Registered Model"},
        title="Update Registered Model",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the registered model.")
    comment: Optional[str] = Field(None, title="Comment", description="Updated free-form comment.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the new owner of the model.")


async def _update_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/models/{c.full_name}",
        json_body={
            "new_name": c.new_name,
            "comment": c.comment,
            "owner": c.owner,
        },
        action_name="update_registered_model",
    )


class DatabricksDeleteRegisteredModelConfig(BaseModel):
    """Delete a registered model."""
    operation: Literal["delete_registered_model"] = Field(
        "delete_registered_model",
        json_schema_extra={"const": "delete_registered_model", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Delete Registered Model"},
        title="Delete Registered Model",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")


async def _delete_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/models/{c.full_name}",
        action_name="delete_registered_model",
    )


class DatabricksSetRegisteredModelAliasConfig(BaseModel):
    """Set an alias on a registered model pointing to a version."""
    operation: Literal["set_registered_model_alias"] = Field(
        "set_registered_model_alias",
        json_schema_extra={"const": "set_registered_model_alias", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Set Registered Model Alias"},
        title="Set Registered Model Alias",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    alias: str = Field(..., title="Alias", description="The name of the alias to set.")
    version_num: int = Field(..., title="Version Number", description="The model version number the alias points to.")


async def _set_registered_model_alias(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PUT", f"/api/2.1/unity-catalog/models/{c.full_name}/aliases/{c.alias}",
        json_body={"version_num": c.version_num},
        action_name="set_registered_model_alias",
    )


class DatabricksDeleteRegisteredModelAliasConfig(BaseModel):
    """Delete an alias from a registered model."""
    operation: Literal["delete_registered_model_alias"] = Field(
        "delete_registered_model_alias",
        json_schema_extra={"const": "delete_registered_model_alias", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Delete Registered Model Alias"},
        title="Delete Registered Model Alias",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    alias: str = Field(..., title="Alias", description="The name of the alias to delete.")


async def _delete_registered_model_alias(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/models/{c.full_name}/aliases/{c.alias}",
        action_name="delete_registered_model_alias",
    )


class DatabricksListModelVersionsConfig(BaseModel):
    """List versions of a registered model."""
    operation: Literal["list_model_versions"] = Field(
        "list_model_versions",
        json_schema_extra={"const": "list_model_versions", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "List Model Versions"},
        title="List Model Versions",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    max_results: Optional[int] = Field(None, title="Max Results", description="Maximum number of versions to return.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque pagination token from a prior response.")


async def _list_model_versions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/models/{c.full_name}/versions",
        params={"max_results": c.max_results, "page_token": c.page_token},
        action_name="list_model_versions",
    )


class DatabricksGetModelVersionConfig(BaseModel):
    """Get a specific model version by number."""
    operation: Literal["get_model_version"] = Field(
        "get_model_version",
        json_schema_extra={"const": "get_model_version", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Get Model Version"},
        title="Get Model Version",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    version: int = Field(..., title="Version", description="The integer version number of the model version.")


async def _get_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/models/{c.full_name}/versions/{c.version}",
        action_name="get_model_version",
    )


class DatabricksGetModelVersionByAliasConfig(BaseModel):
    """Get a model version by alias."""
    operation: Literal["get_model_version_by_alias"] = Field(
        "get_model_version_by_alias",
        json_schema_extra={"const": "get_model_version_by_alias", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Get Model Version By Alias"},
        title="Get Model Version By Alias",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    alias: str = Field(..., title="Alias", description="The name of the alias to resolve.")


async def _get_model_version_by_alias(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/models/{c.full_name}/aliases/{c.alias}",
        action_name="get_model_version_by_alias",
    )


class DatabricksUpdateModelVersionConfig(BaseModel):
    """Update a model version's comment."""
    operation: Literal["update_model_version"] = Field(
        "update_model_version",
        json_schema_extra={"const": "update_model_version", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Update Model Version"},
        title="Update Model Version",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    version: int = Field(..., title="Version", description="The integer version number of the model version.")
    comment: Optional[str] = Field(None, title="Comment", description="Updated free-form comment for the version.")


async def _update_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/models/{c.full_name}/versions/{c.version}",
        json_body={"comment": c.comment},
        action_name="update_model_version",
    )


class DatabricksDeleteModelVersionConfig(BaseModel):
    """Delete a model version."""
    operation: Literal["delete_model_version"] = Field(
        "delete_model_version",
        json_schema_extra={"const": "delete_model_version", "ui:hidden": True,
                           "x-category": "Unity Catalog Models", "x-is-trigger": False,
                           "x-display-name": "Delete Model Version"},
        title="Delete Model Version",
    )
    full_name: str = Field(..., title="Full Name", description="Three-level name of the model (catalog.schema.model).")
    version: int = Field(..., title="Version", description="The integer version number of the model version.")


async def _delete_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/models/{c.full_name}/versions/{c.version}",
        action_name="delete_model_version",
    )


OPERATION_CONFIGS.extend([
    DatabricksListRegisteredModelsConfig,
    DatabricksCreateRegisteredModelConfig,
    DatabricksGetRegisteredModelConfig,
    DatabricksUpdateRegisteredModelConfig,
    DatabricksDeleteRegisteredModelConfig,
    DatabricksSetRegisteredModelAliasConfig,
    DatabricksDeleteRegisteredModelAliasConfig,
    DatabricksListModelVersionsConfig,
    DatabricksGetModelVersionConfig,
    DatabricksGetModelVersionByAliasConfig,
    DatabricksUpdateModelVersionConfig,
    DatabricksDeleteModelVersionConfig,
])
OPERATION_HANDLERS.update({
    "list_registered_models": _list_registered_models,
    "create_registered_model": _create_registered_model,
    "get_registered_model": _get_registered_model,
    "update_registered_model": _update_registered_model,
    "delete_registered_model": _delete_registered_model,
    "set_registered_model_alias": _set_registered_model_alias,
    "delete_registered_model_alias": _delete_registered_model_alias,
    "list_model_versions": _list_model_versions,
    "get_model_version": _get_model_version,
    "get_model_version_by_alias": _get_model_version_by_alias,
    "update_model_version": _update_model_version,
    "delete_model_version": _delete_model_version,
})


# ---- Unity Catalog (11 ops) ----
class DatabricksListExternalLocationsConfig(BaseModel):
    """List external locations in the Unity Catalog metastore."""
    operation: Literal["list_external_locations"] = Field(
        "list_external_locations",
        json_schema_extra={"const": "list_external_locations", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List External Locations"},
        title="List External Locations",
    )
    max_results: Optional[str] = Field(None, title="Max Results", description="Maximum number of external locations to return.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque pagination token to retrieve the next page of results.")
    include_browse: str = Field(
        "false", title="Include Browse",
        description="Whether to include external locations the caller can only browse.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_external_locations(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/external-locations",
        params={
            "max_results": c.max_results,
            "page_token": c.page_token,
            "include_browse": c.include_browse == "true",
        },
        action_name="list_external_locations",
    )


class DatabricksCreateExternalLocationConfig(BaseModel):
    """Create a new external location in Unity Catalog."""
    operation: Literal["create_external_location"] = Field(
        "create_external_location",
        json_schema_extra={"const": "create_external_location", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create External Location"},
        title="Create External Location",
    )
    name: str = Field(..., title="Name", description="Name of the external location.")
    url: str = Field(..., title="URL", description="Path URL of the external location (e.g. s3://bucket/path).")
    credential_name: str = Field(..., title="Storage Credential Name", description="Name of the storage credential used to access the location.")
    comment: Optional[str] = Field(None, title="Comment", description="User-supplied free-form text.")
    read_only: str = Field(
        "false", title="Read Only", description="Whether the external location is read-only.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    skip_validation: str = Field(
        "false", title="Skip Validation", description="Skip validation of the storage credential against the URL.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _create_external_location(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/external-locations",
        json_body={
            "name": c.name,
            "url": c.url,
            "credential_name": c.credential_name,
            "comment": c.comment,
            "read_only": c.read_only == "true",
            "skip_validation": c.skip_validation == "true",
        },
        action_name="create_external_location",
    )


class DatabricksGetExternalLocationConfig(BaseModel):
    """Get an external location by name."""
    operation: Literal["get_external_location"] = Field(
        "get_external_location",
        json_schema_extra={"const": "get_external_location", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get External Location"},
        title="Get External Location",
    )
    name: str = Field(..., title="Name", description="Name of the external location to retrieve.")
    include_browse: str = Field(
        "false", title="Include Browse",
        description="Whether to include the external location if the caller can only browse it.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _get_external_location(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/external-locations/{c.name}",
        params={"include_browse": c.include_browse == "true"},
        action_name="get_external_location",
    )


class DatabricksUpdateExternalLocationConfig(BaseModel):
    """Update an existing external location."""
    operation: Literal["update_external_location"] = Field(
        "update_external_location",
        json_schema_extra={"const": "update_external_location", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update External Location"},
        title="Update External Location",
    )
    name: str = Field(..., title="Name", description="Name of the external location to update.")
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the external location.")
    url: Optional[str] = Field(None, title="URL", description="New path URL of the external location.")
    credential_name: Optional[str] = Field(None, title="Storage Credential Name", description="New storage credential name.")
    comment: Optional[str] = Field(None, title="Comment", description="User-supplied free-form text.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the external location owner.")
    read_only: Optional[str] = Field(
        None, title="Read Only", description="Whether the external location is read-only.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _update_external_location(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/external-locations/{c.name}",
        json_body={
            "new_name": c.new_name,
            "url": c.url,
            "credential_name": c.credential_name,
            "comment": c.comment,
            "owner": c.owner,
            "read_only": None if c.read_only is None else c.read_only == "true",
        },
        action_name="update_external_location",
    )


class DatabricksDeleteExternalLocationConfig(BaseModel):
    """Delete an external location."""
    operation: Literal["delete_external_location"] = Field(
        "delete_external_location",
        json_schema_extra={"const": "delete_external_location", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete External Location"},
        title="Delete External Location",
    )
    name: str = Field(..., title="Name", description="Name of the external location to delete.")
    force: str = Field(
        "false", title="Force", description="Force deletion even if dependent resources exist.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _delete_external_location(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/external-locations/{c.name}",
        params={"force": c.force == "true"},
        action_name="delete_external_location",
    )


class DatabricksListStorageCredentialsConfig(BaseModel):
    """List storage credentials in the Unity Catalog metastore."""
    operation: Literal["list_storage_credentials"] = Field(
        "list_storage_credentials",
        json_schema_extra={"const": "list_storage_credentials", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Storage Credentials"},
        title="List Storage Credentials",
    )
    max_results: Optional[str] = Field(None, title="Max Results", description="Maximum number of storage credentials to return.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque pagination token to retrieve the next page of results.")


async def _list_storage_credentials(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.1/unity-catalog/storage-credentials",
        params={"max_results": c.max_results, "page_token": c.page_token},
        action_name="list_storage_credentials",
    )


class DatabricksCreateStorageCredentialConfig(BaseModel):
    """Create a new storage credential in Unity Catalog."""
    operation: Literal["create_storage_credential"] = Field(
        "create_storage_credential",
        json_schema_extra={"const": "create_storage_credential", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Storage Credential"},
        title="Create Storage Credential",
    )
    name: str = Field(..., title="Name", description="Name of the storage credential.")
    comment: Optional[str] = Field(None, title="Comment", description="User-supplied free-form text.")
    read_only: str = Field(
        "false", title="Read Only", description="Whether the storage credential is read-only.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    skip_validation: str = Field(
        "false", title="Skip Validation", description="Skip validation of the credential.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    credential_json: str = Field(
        "{}", title="Credential (JSON)",
        description="Credential body, e.g. {\"aws_iam_role\": {\"role_arn\": \"...\"}} or {\"azure_managed_identity\": {...}}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_storage_credential(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.credential_json, "Credential") or {}
    body["name"] = c.name
    body["comment"] = c.comment
    body["read_only"] = c.read_only == "true"
    body["skip_validation"] = c.skip_validation == "true"
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/storage-credentials",
        json_body=body, action_name="create_storage_credential",
    )


class DatabricksGetStorageCredentialConfig(BaseModel):
    """Get a storage credential by name."""
    operation: Literal["get_storage_credential"] = Field(
        "get_storage_credential",
        json_schema_extra={"const": "get_storage_credential", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Storage Credential"},
        title="Get Storage Credential",
    )
    name: str = Field(..., title="Name", description="Name of the storage credential to retrieve.")


async def _get_storage_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.1/unity-catalog/storage-credentials/{c.name}",
        action_name="get_storage_credential",
    )


class DatabricksUpdateStorageCredentialConfig(BaseModel):
    """Update an existing storage credential."""
    operation: Literal["update_storage_credential"] = Field(
        "update_storage_credential",
        json_schema_extra={"const": "update_storage_credential", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Storage Credential"},
        title="Update Storage Credential",
    )
    name: str = Field(..., title="Name", description="Name of the storage credential to update.")
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the storage credential.")
    comment: Optional[str] = Field(None, title="Comment", description="User-supplied free-form text.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the storage credential owner.")
    read_only: Optional[str] = Field(
        None, title="Read Only", description="Whether the storage credential is read-only.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    credential_json: str = Field(
        "{}", title="Credential (JSON)",
        description="Optional new credential body (e.g. {\"aws_iam_role\": {...}}). Leave as {} to keep unchanged.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_storage_credential(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.credential_json, "Credential") or {}
    body["new_name"] = c.new_name
    body["comment"] = c.comment
    body["owner"] = c.owner
    body["read_only"] = None if c.read_only is None else c.read_only == "true"
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.1/unity-catalog/storage-credentials/{c.name}",
        json_body=body, action_name="update_storage_credential",
    )


class DatabricksDeleteStorageCredentialConfig(BaseModel):
    """Delete a storage credential."""
    operation: Literal["delete_storage_credential"] = Field(
        "delete_storage_credential",
        json_schema_extra={"const": "delete_storage_credential", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Storage Credential"},
        title="Delete Storage Credential",
    )
    name: str = Field(..., title="Name", description="Name of the storage credential to delete.")
    force: str = Field(
        "false", title="Force", description="Force deletion even if dependent external locations exist.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _delete_storage_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.1/unity-catalog/storage-credentials/{c.name}",
        params={"force": c.force == "true"},
        action_name="delete_storage_credential",
    )


class DatabricksValidateStorageCredentialConfig(BaseModel):
    """Validate a storage credential against a location or self-hosted URL."""
    operation: Literal["validate_storage_credential"] = Field(
        "validate_storage_credential",
        json_schema_extra={"const": "validate_storage_credential", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Validate Storage Credential"},
        title="Validate Storage Credential",
    )
    validate_json: str = Field(
        "{}", title="Validation Request (JSON)",
        description="Full validation request body, e.g. {\"storage_credential_name\": \"...\", \"external_location_name\": \"...\", \"url\": \"...\"} or an inline credential to validate.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _validate_storage_credential(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.validate_json, "Validation Request") or {}
    return await _databricks_request(
        host, token, "POST", "/api/2.1/unity-catalog/validate-storage-credentials",
        json_body=body, action_name="validate_storage_credential",
    )


OPERATION_CONFIGS.extend([
    DatabricksListExternalLocationsConfig,
    DatabricksCreateExternalLocationConfig,
    DatabricksGetExternalLocationConfig,
    DatabricksUpdateExternalLocationConfig,
    DatabricksDeleteExternalLocationConfig,
    DatabricksListStorageCredentialsConfig,
    DatabricksCreateStorageCredentialConfig,
    DatabricksGetStorageCredentialConfig,
    DatabricksUpdateStorageCredentialConfig,
    DatabricksDeleteStorageCredentialConfig,
    DatabricksValidateStorageCredentialConfig,
])
OPERATION_HANDLERS.update({
    "list_external_locations": _list_external_locations,
    "create_external_location": _create_external_location,
    "get_external_location": _get_external_location,
    "update_external_location": _update_external_location,
    "delete_external_location": _delete_external_location,
    "list_storage_credentials": _list_storage_credentials,
    "create_storage_credential": _create_storage_credential,
    "get_storage_credential": _get_storage_credential,
    "update_storage_credential": _update_storage_credential,
    "delete_storage_credential": _delete_storage_credential,
    "validate_storage_credential": _validate_storage_credential,
})


# ---- Unity Catalog (12 ops) ----
class DatabricksListConnectionsConfig(BaseModel):
    """List all Unity Catalog connections in the metastore."""
    operation: Literal["list_connections"] = Field(
        "list_connections",
        json_schema_extra={"const": "list_connections", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Connections"},
        title="List Connections",
    )


async def _list_connections(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/unity-catalog/connections", action_name="list_connections")


class DatabricksCreateConnectionConfig(BaseModel):
    """Create a new Unity Catalog connection to an external data system."""
    operation: Literal["create_connection"] = Field(
        "create_connection",
        json_schema_extra={"const": "create_connection", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Connection"},
        title="Create Connection",
    )
    name: str = Field(..., title="Connection Name", description="Name of the connection to create.")
    connection_type: str = Field(
        ..., title="Connection Type",
        description="The type of connection.",
        json_schema_extra={
            "enum": ["MYSQL", "POSTGRESQL", "SNOWFLAKE", "REDSHIFT", "SQLDW", "SQLSERVER",
                     "DATABRICKS", "BIGQUERY", "HIVE_METASTORE", "GLUE", "TERADATA", "ORACLE",
                     "SALESFORCE", "HTTP", "POWER_BI"],
            "x-enum-searchable": True,
        },
    )
    options_json: str = Field(
        "{}", title="Options (JSON)",
        description="Connection-type-specific options (e.g. host, port, user, password) as a JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    comment: Optional[str] = Field(None, title="Comment", description="User-provided free-form text description.")
    read_only: str = Field(
        "false", title="Read Only", description="Whether the connection is read-only.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    properties_json: Optional[str] = Field(
        None, title="Properties (JSON)",
        description="Optional free-form key-value properties as a JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_connection(c, host, token) -> Dict[str, Any]:
    body = {
        "name": c.name,
        "connection_type": c.connection_type,
        "options": _parse_json_field(c.options_json, "Options") or {},
        "comment": c.comment,
        "read_only": c.read_only == "true",
        "properties": _parse_json_field(c.properties_json, "Properties"),
    }
    return await _databricks_request(host, token, "POST", "/api/2.1/unity-catalog/connections", json_body=body, action_name="create_connection")


class DatabricksGetConnectionConfig(BaseModel):
    """Get a Unity Catalog connection by name."""
    operation: Literal["get_connection"] = Field(
        "get_connection",
        json_schema_extra={"const": "get_connection", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Connection"},
        title="Get Connection",
    )
    name: str = Field(..., title="Connection Name", description="Name of the connection to retrieve.")


async def _get_connection(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/connections/{c.name}", action_name="get_connection")


class DatabricksUpdateConnectionConfig(BaseModel):
    """Update an existing Unity Catalog connection."""
    operation: Literal["update_connection"] = Field(
        "update_connection",
        json_schema_extra={"const": "update_connection", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Connection"},
        title="Update Connection",
    )
    name: str = Field(..., title="Connection Name", description="Current name of the connection to update.")
    new_name: Optional[str] = Field(None, title="New Name", description="New name to rename the connection to.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the new owner of the connection.")
    options_json: Optional[str] = Field(
        None, title="Options (JSON)",
        description="Updated connection options as a JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_connection(c, host, token) -> Dict[str, Any]:
    body = {
        "new_name": c.new_name,
        "owner": c.owner,
        "options": _parse_json_field(c.options_json, "Options"),
    }
    return await _databricks_request(host, token, "PATCH", f"/api/2.1/unity-catalog/connections/{c.name}", json_body=body, action_name="update_connection")


class DatabricksDeleteConnectionConfig(BaseModel):
    """Delete a Unity Catalog connection by name."""
    operation: Literal["delete_connection"] = Field(
        "delete_connection",
        json_schema_extra={"const": "delete_connection", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Connection"},
        title="Delete Connection",
    )
    name: str = Field(..., title="Connection Name", description="Name of the connection to delete.")


async def _delete_connection(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.1/unity-catalog/connections/{c.name}", action_name="delete_connection")


class DatabricksListMetastoresConfig(BaseModel):
    """List all Unity Catalog metastores the caller has access to."""
    operation: Literal["list_metastores"] = Field(
        "list_metastores",
        json_schema_extra={"const": "list_metastores", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "List Metastores"},
        title="List Metastores",
    )


async def _list_metastores(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/unity-catalog/metastores", action_name="list_metastores")


class DatabricksCreateMetastoreConfig(BaseModel):
    """Create a new Unity Catalog metastore."""
    operation: Literal["create_metastore"] = Field(
        "create_metastore",
        json_schema_extra={"const": "create_metastore", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Create Metastore"},
        title="Create Metastore",
    )
    name: str = Field(..., title="Metastore Name", description="Name of the metastore to create.")
    storage_root: Optional[str] = Field(None, title="Storage Root", description="Cloud storage root path (e.g. s3:// or abfss://) for managed tables.")
    region: Optional[str] = Field(None, title="Region", description="Cloud region in which the metastore is located.")


async def _create_metastore(c, host, token) -> Dict[str, Any]:
    body = {
        "name": c.name,
        "storage_root": c.storage_root,
        "region": c.region,
    }
    return await _databricks_request(host, token, "POST", "/api/2.1/unity-catalog/metastores", json_body=body, action_name="create_metastore")


class DatabricksGetMetastoreConfig(BaseModel):
    """Get a Unity Catalog metastore by ID."""
    operation: Literal["get_metastore"] = Field(
        "get_metastore",
        json_schema_extra={"const": "get_metastore", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Metastore"},
        title="Get Metastore",
    )
    metastore_id: str = Field(..., title="Metastore ID", description="Unique ID of the metastore to retrieve.")


async def _get_metastore(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/metastores/{c.metastore_id}", action_name="get_metastore")


class DatabricksUpdateMetastoreConfig(BaseModel):
    """Update an existing Unity Catalog metastore."""
    operation: Literal["update_metastore"] = Field(
        "update_metastore",
        json_schema_extra={"const": "update_metastore", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Update Metastore"},
        title="Update Metastore",
    )
    metastore_id: str = Field(..., title="Metastore ID", description="Unique ID of the metastore to update.")
    new_name: Optional[str] = Field(None, title="New Name", description="New name to rename the metastore to.")
    owner: Optional[str] = Field(None, title="Owner", description="Username of the new owner of the metastore.")
    delta_sharing_scope: Optional[str] = Field(
        None, title="Delta Sharing Scope",
        description="The scope of Delta Sharing enabled for the metastore.",
        json_schema_extra={
            "enum": ["INTERNAL", "INTERNAL_AND_EXTERNAL"],
            "x-enum-searchable": True,
        },
    )


async def _update_metastore(c, host, token) -> Dict[str, Any]:
    body = {
        "new_name": c.new_name,
        "owner": c.owner,
        "delta_sharing_scope": c.delta_sharing_scope,
    }
    return await _databricks_request(host, token, "PATCH", f"/api/2.1/unity-catalog/metastores/{c.metastore_id}", json_body=body, action_name="update_metastore")


class DatabricksDeleteMetastoreConfig(BaseModel):
    """Delete a Unity Catalog metastore by ID."""
    operation: Literal["delete_metastore"] = Field(
        "delete_metastore",
        json_schema_extra={"const": "delete_metastore", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Delete Metastore"},
        title="Delete Metastore",
    )
    metastore_id: str = Field(..., title="Metastore ID", description="Unique ID of the metastore to delete.")
    force: str = Field(
        "false", title="Force", description="Force deletion even if the metastore is not empty.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _delete_metastore(c, host, token) -> Dict[str, Any]:
    params = {"force": c.force == "true"}
    return await _databricks_request(host, token, "DELETE", f"/api/2.1/unity-catalog/metastores/{c.metastore_id}", params=params, action_name="delete_metastore")


class DatabricksGetCurrentMetastoreAssignmentConfig(BaseModel):
    """Get the metastore assignment for the current workspace."""
    operation: Literal["get_current_metastore_assignment"] = Field(
        "get_current_metastore_assignment",
        json_schema_extra={"const": "get_current_metastore_assignment", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Current Metastore Assignment"},
        title="Get Current Metastore Assignment",
    )


async def _get_current_metastore_assignment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/unity-catalog/current-metastore-assignment", action_name="get_current_metastore_assignment")


class DatabricksGetMetastoreSummaryConfig(BaseModel):
    """Get summary information about the metastore assigned to the current workspace."""
    operation: Literal["get_metastore_summary"] = Field(
        "get_metastore_summary",
        json_schema_extra={"const": "get_metastore_summary", "ui:hidden": True,
                           "x-category": "Unity Catalog", "x-is-trigger": False,
                           "x-display-name": "Get Metastore Summary"},
        title="Get Metastore Summary",
    )


async def _get_metastore_summary(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.1/unity-catalog/metastore_summary", action_name="get_metastore_summary")


OPERATION_CONFIGS.extend([
    DatabricksListConnectionsConfig,
    DatabricksCreateConnectionConfig,
    DatabricksGetConnectionConfig,
    DatabricksUpdateConnectionConfig,
    DatabricksDeleteConnectionConfig,
    DatabricksListMetastoresConfig,
    DatabricksCreateMetastoreConfig,
    DatabricksGetMetastoreConfig,
    DatabricksUpdateMetastoreConfig,
    DatabricksDeleteMetastoreConfig,
    DatabricksGetCurrentMetastoreAssignmentConfig,
    DatabricksGetMetastoreSummaryConfig,
])
OPERATION_HANDLERS.update({
    "list_connections": _list_connections,
    "create_connection": _create_connection,
    "get_connection": _get_connection,
    "update_connection": _update_connection,
    "delete_connection": _delete_connection,
    "list_metastores": _list_metastores,
    "create_metastore": _create_metastore,
    "get_metastore": _get_metastore,
    "update_metastore": _update_metastore,
    "delete_metastore": _delete_metastore,
    "get_current_metastore_assignment": _get_current_metastore_assignment,
    "get_metastore_summary": _get_metastore_summary,
})


# ---- Unity Catalog Grants (11 ops) ----
class DatabricksGetGrantsConfig(BaseModel):
    """Get permissions on a securable object in Unity Catalog."""
    operation: Literal["get_grants"] = Field(
        "get_grants",
        json_schema_extra={"const": "get_grants", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Get Grants"},
        title="Get Grants",
    )
    securable_type: str = Field(
        ...,
        title="Securable Type",
        description="Type of securable to fetch permissions for",
        json_schema_extra={
            "enum": ["catalog", "schema", "table", "storage_credential",
                     "external_location", "function", "share", "provider",
                     "recipient", "metastore", "volume", "registered_model",
                     "connection", "credential", "pipeline", "clean_room"],
            "x-enum-searchable": True,
        },
    )
    full_name: str = Field(
        ...,
        title="Securable Full Name",
        description="Full name of the securable (e.g. catalog.schema.table)",
    )
    principal: Optional[str] = Field(
        None,
        title="Principal",
        description="Optional user/group/service-principal to filter grants for",
    )


class DatabricksUpdateGrantsConfig(BaseModel):
    """Update permissions on a securable object in Unity Catalog."""
    operation: Literal["update_grants"] = Field(
        "update_grants",
        json_schema_extra={"const": "update_grants", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Update Grants"},
        title="Update Grants",
    )
    securable_type: str = Field(
        ...,
        title="Securable Type",
        description="Type of securable to update permissions for",
        json_schema_extra={
            "enum": ["catalog", "schema", "table", "storage_credential",
                     "external_location", "function", "share", "provider",
                     "recipient", "metastore", "volume", "registered_model",
                     "connection", "credential", "pipeline", "clean_room"],
            "x-enum-searchable": True,
        },
    )
    full_name: str = Field(
        ...,
        title="Securable Full Name",
        description="Full name of the securable (e.g. catalog.schema.table)",
    )
    changes_json: str = Field(
        "[]",
        title="Permission Changes (JSON)",
        description='Array of change objects, e.g. [{"principal":"user@x.com","add":["SELECT"],"remove":["MODIFY"]}]',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetEffectiveGrantsConfig(BaseModel):
    """Get effective (inherited) permissions on a securable in Unity Catalog."""
    operation: Literal["get_effective_grants"] = Field(
        "get_effective_grants",
        json_schema_extra={"const": "get_effective_grants", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Get Effective Grants"},
        title="Get Effective Grants",
    )
    securable_type: str = Field(
        ...,
        title="Securable Type",
        description="Type of securable to fetch effective permissions for",
        json_schema_extra={
            "enum": ["catalog", "schema", "table", "storage_credential",
                     "external_location", "function", "share", "provider",
                     "recipient", "metastore", "volume", "registered_model",
                     "connection", "credential", "pipeline", "clean_room"],
            "x-enum-searchable": True,
        },
    )
    full_name: str = Field(
        ...,
        title="Securable Full Name",
        description="Full name of the securable (e.g. catalog.schema.table)",
    )
    principal: Optional[str] = Field(
        None,
        title="Principal",
        description="Optional user/group/service-principal to filter effective grants for",
    )


class DatabricksListSystemSchemasConfig(BaseModel):
    """List system schemas for a metastore."""
    operation: Literal["list_system_schemas"] = Field(
        "list_system_schemas",
        json_schema_extra={"const": "list_system_schemas", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "List System Schemas"},
        title="List System Schemas",
    )
    metastore_id: str = Field(
        ...,
        title="Metastore ID",
        description="Unique identifier of the metastore",
    )


class DatabricksEnableSystemSchemaConfig(BaseModel):
    """Enable a system schema for a metastore."""
    operation: Literal["enable_system_schema"] = Field(
        "enable_system_schema",
        json_schema_extra={"const": "enable_system_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Enable System Schema"},
        title="Enable System Schema",
    )
    metastore_id: str = Field(
        ...,
        title="Metastore ID",
        description="Unique identifier of the metastore",
    )
    schema_name: str = Field(
        ...,
        title="Schema Name",
        description="Name of the system schema to enable (e.g. access, billing)",
    )


class DatabricksDisableSystemSchemaConfig(BaseModel):
    """Disable a system schema for a metastore."""
    operation: Literal["disable_system_schema"] = Field(
        "disable_system_schema",
        json_schema_extra={"const": "disable_system_schema", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Disable System Schema"},
        title="Disable System Schema",
    )
    metastore_id: str = Field(
        ...,
        title="Metastore ID",
        description="Unique identifier of the metastore",
    )
    schema_name: str = Field(
        ...,
        title="Schema Name",
        description="Name of the system schema to disable (e.g. access, billing)",
    )


class DatabricksGetArtifactAllowlistConfig(BaseModel):
    """Get the artifact allowlist of a certain artifact type in the metastore."""
    operation: Literal["get_artifact_allowlist"] = Field(
        "get_artifact_allowlist",
        json_schema_extra={"const": "get_artifact_allowlist", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Get Artifact Allowlist"},
        title="Get Artifact Allowlist",
    )
    artifact_type: str = Field(
        ...,
        title="Artifact Type",
        description="Type of artifact allowlist to fetch",
        json_schema_extra={
            "enum": ["INIT_SCRIPT", "LIBRARY_JAR", "LIBRARY_MAVEN"],
            "x-enum-searchable": True,
        },
    )


class DatabricksSetArtifactAllowlistConfig(BaseModel):
    """Set the artifact allowlist of a certain artifact type in the metastore."""
    operation: Literal["set_artifact_allowlist"] = Field(
        "set_artifact_allowlist",
        json_schema_extra={"const": "set_artifact_allowlist", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Set Artifact Allowlist"},
        title="Set Artifact Allowlist",
    )
    artifact_type: str = Field(
        ...,
        title="Artifact Type",
        description="Type of artifact allowlist to set",
        json_schema_extra={
            "enum": ["INIT_SCRIPT", "LIBRARY_JAR", "LIBRARY_MAVEN"],
            "x-enum-searchable": True,
        },
    )
    artifact_matchers_json: str = Field(
        "[]",
        title="Artifact Matchers (JSON)",
        description='Array of matcher objects, e.g. [{"artifact":"/Volumes/x/y/z","match_type":"PREFIX_MATCH"}]',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksListResourceQuotasConfig(BaseModel):
    """List all resource quotas under a metastore."""
    operation: Literal["list_resource_quotas"] = Field(
        "list_resource_quotas",
        json_schema_extra={"const": "list_resource_quotas", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "List Resource Quotas"},
        title="List Resource Quotas",
    )
    next_page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="Opaque token to retrieve the next page of results",
    )


class DatabricksCreateTableConstraintConfig(BaseModel):
    """Create a primary-key, foreign-key, or check constraint on a table."""
    operation: Literal["create_table_constraint"] = Field(
        "create_table_constraint",
        json_schema_extra={"const": "create_table_constraint", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Create Table Constraint"},
        title="Create Table Constraint",
    )
    full_name_arg: str = Field(
        ...,
        title="Table Full Name",
        description="Full name of the table (catalog.schema.table) to add the constraint to",
    )
    constraint_json: str = Field(
        "{}",
        title="Constraint (JSON)",
        description='Constraint spec, e.g. {"primary_key_constraint":{"name":"pk","child_columns":["id"]}}',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeleteTableConstraintConfig(BaseModel):
    """Delete a named constraint from a table."""
    operation: Literal["delete_table_constraint"] = Field(
        "delete_table_constraint",
        json_schema_extra={"const": "delete_table_constraint", "ui:hidden": True,
                           "x-category": "Unity Catalog Grants", "x-is-trigger": False,
                           "x-display-name": "Delete Table Constraint"},
        title="Delete Table Constraint",
    )
    full_name: str = Field(
        ...,
        title="Table Full Name",
        description="Full name of the table (catalog.schema.table) to remove the constraint from",
    )
    constraint_name: str = Field(
        ...,
        title="Constraint Name",
        description="Name of the constraint to delete",
    )
    cascade: str = Field(
        "false",
        title="Cascade",
        description="Also delete constraints dependent on this one",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"],
                           "x-enum-searchable": True},
    )


async def _get_grants(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.1/unity-catalog/permissions/{c.securable_type}/{c.full_name}",
        params={"principal": c.principal},
        action_name="get_grants",
    )


async def _update_grants(c, host, token) -> Dict[str, Any]:
    changes = _parse_json_field(c.changes_json, "Permission Changes") or []
    return await _databricks_request(
        host, token, "PATCH",
        f"/api/2.1/unity-catalog/permissions/{c.securable_type}/{c.full_name}",
        json_body={"changes": changes},
        action_name="update_grants",
    )


async def _get_effective_grants(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.1/unity-catalog/effective-permissions/{c.securable_type}/{c.full_name}",
        params={"principal": c.principal},
        action_name="get_effective_grants",
    )


async def _list_system_schemas(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.1/unity-catalog/metastores/{c.metastore_id}/systemschemas",
        action_name="list_system_schemas",
    )


async def _enable_system_schema(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PUT",
        f"/api/2.1/unity-catalog/metastores/{c.metastore_id}/systemschemas/{c.schema_name}",
        action_name="enable_system_schema",
    )


async def _disable_system_schema(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE",
        f"/api/2.1/unity-catalog/metastores/{c.metastore_id}/systemschemas/{c.schema_name}",
        action_name="disable_system_schema",
    )


async def _get_artifact_allowlist(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.1/unity-catalog/artifact-allowlists/{c.artifact_type}",
        action_name="get_artifact_allowlist",
    )


async def _set_artifact_allowlist(c, host, token) -> Dict[str, Any]:
    matchers = _parse_json_field(c.artifact_matchers_json, "Artifact Matchers") or []
    return await _databricks_request(
        host, token, "PUT",
        f"/api/2.1/unity-catalog/artifact-allowlists/{c.artifact_type}",
        json_body={"artifact_matchers": matchers},
        action_name="set_artifact_allowlist",
    )


async def _list_resource_quotas(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        "/api/2.1/unity-catalog/resource-quotas/all-resource-quotas",
        params={"page_token": c.next_page_token},
        action_name="list_resource_quotas",
    )


async def _create_table_constraint(c, host, token) -> Dict[str, Any]:
    constraint = _parse_json_field(c.constraint_json, "Constraint") or {}
    return await _databricks_request(
        host, token, "POST",
        "/api/2.1/unity-catalog/constraints",
        json_body={"full_name_arg": c.full_name_arg, "constraint": constraint},
        action_name="create_table_constraint",
    )


async def _delete_table_constraint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE",
        f"/api/2.1/unity-catalog/constraints/{c.full_name}",
        params={"constraint_name": c.constraint_name, "cascade": c.cascade == "true"},
        action_name="delete_table_constraint",
    )


OPERATION_CONFIGS.extend([
    DatabricksGetGrantsConfig,
    DatabricksUpdateGrantsConfig,
    DatabricksGetEffectiveGrantsConfig,
    DatabricksListSystemSchemasConfig,
    DatabricksEnableSystemSchemaConfig,
    DatabricksDisableSystemSchemaConfig,
    DatabricksGetArtifactAllowlistConfig,
    DatabricksSetArtifactAllowlistConfig,
    DatabricksListResourceQuotasConfig,
    DatabricksCreateTableConstraintConfig,
    DatabricksDeleteTableConstraintConfig,
])
OPERATION_HANDLERS.update({
    "get_grants": _get_grants,
    "update_grants": _update_grants,
    "get_effective_grants": _get_effective_grants,
    "list_system_schemas": _list_system_schemas,
    "enable_system_schema": _enable_system_schema,
    "disable_system_schema": _disable_system_schema,
    "get_artifact_allowlist": _get_artifact_allowlist,
    "set_artifact_allowlist": _set_artifact_allowlist,
    "list_resource_quotas": _list_resource_quotas,
    "create_table_constraint": _create_table_constraint,
    "delete_table_constraint": _delete_table_constraint,
})


# ---- Unity Catalog Monitoring (12 ops) ----
class DatabricksCreateQualityMonitorConfig(BaseModel):
    """Create a Lakehouse Monitor for a Unity Catalog table."""
    operation: Literal["create_quality_monitor"] = Field(
        "create_quality_monitor",
        json_schema_extra={"const": "create_quality_monitor", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Create Quality Monitor"},
        title="Create Quality Monitor",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the table to monitor (catalog.schema.table).")
    assets_dir: str = Field(..., title="Assets Directory", description="Directory (workspace path) to store monitoring assets such as the dashboard.")
    output_schema_name: str = Field(..., title="Output Schema Name", description="Full name of the schema where output metric tables are created (catalog.schema).")
    monitor_json: str = Field("{}", title="Monitor Spec (JSON)", description="Additional monitor body: monitor type (snapshot / time_series / inference_log), schedule, notifications, slicing_exprs, etc.",
                              json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_quality_monitor(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.monitor_json, "Monitor Spec") or {}
    body["assets_dir"] = c.assets_dir
    body["output_schema_name"] = c.output_schema_name
    return await _databricks_request(host, token, "POST", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor", json_body=body, action_name="create_quality_monitor")


class DatabricksGetQualityMonitorConfig(BaseModel):
    """Get the Lakehouse Monitor for a Unity Catalog table."""
    operation: Literal["get_quality_monitor"] = Field(
        "get_quality_monitor",
        json_schema_extra={"const": "get_quality_monitor", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Get Quality Monitor"},
        title="Get Quality Monitor",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")


async def _get_quality_monitor(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor", action_name="get_quality_monitor")


class DatabricksUpdateQualityMonitorConfig(BaseModel):
    """Update the Lakehouse Monitor for a Unity Catalog table."""
    operation: Literal["update_quality_monitor"] = Field(
        "update_quality_monitor",
        json_schema_extra={"const": "update_quality_monitor", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Update Quality Monitor"},
        title="Update Quality Monitor",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")
    output_schema_name: Optional[str] = Field(None, title="Output Schema Name", description="Full name of the schema where output metric tables are created (catalog.schema).")
    monitor_json: str = Field("{}", title="Monitor Spec (JSON)", description="Updated monitor body: monitor type, schedule, notifications, slicing_exprs, dashboard_id, etc.",
                              json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_quality_monitor(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.monitor_json, "Monitor Spec") or {}
    if c.output_schema_name is not None:
        body["output_schema_name"] = c.output_schema_name
    return await _databricks_request(host, token, "PUT", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor", json_body=body, action_name="update_quality_monitor")


class DatabricksDeleteQualityMonitorConfig(BaseModel):
    """Delete the Lakehouse Monitor for a Unity Catalog table."""
    operation: Literal["delete_quality_monitor"] = Field(
        "delete_quality_monitor",
        json_schema_extra={"const": "delete_quality_monitor", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Delete Quality Monitor"},
        title="Delete Quality Monitor",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")


async def _delete_quality_monitor(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor", action_name="delete_quality_monitor")


class DatabricksRunQualityMonitorRefreshConfig(BaseModel):
    """Trigger a refresh (metric recomputation) of a table's monitor."""
    operation: Literal["run_quality_monitor_refresh"] = Field(
        "run_quality_monitor_refresh",
        json_schema_extra={"const": "run_quality_monitor_refresh", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Run Quality Monitor Refresh"},
        title="Run Quality Monitor Refresh",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")


async def _run_quality_monitor_refresh(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor/refreshes", json_body={}, action_name="run_quality_monitor_refresh")


class DatabricksListQualityMonitorRefreshesConfig(BaseModel):
    """List refreshes of a table's monitor."""
    operation: Literal["list_quality_monitor_refreshes"] = Field(
        "list_quality_monitor_refreshes",
        json_schema_extra={"const": "list_quality_monitor_refreshes", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "List Quality Monitor Refreshes"},
        title="List Quality Monitor Refreshes",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")


async def _list_quality_monitor_refreshes(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor/refreshes", action_name="list_quality_monitor_refreshes")


class DatabricksGetQualityMonitorRefreshConfig(BaseModel):
    """Get a specific refresh of a table's monitor."""
    operation: Literal["get_quality_monitor_refresh"] = Field(
        "get_quality_monitor_refresh",
        json_schema_extra={"const": "get_quality_monitor_refresh", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Get Quality Monitor Refresh"},
        title="Get Quality Monitor Refresh",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the monitored table (catalog.schema.table).")
    refresh_id: str = Field(..., title="Refresh ID", description="Unique ID of the monitor refresh to retrieve.")


async def _get_quality_monitor_refresh(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.1/unity-catalog/tables/{c.table_name}/monitor/refreshes/{c.refresh_id}", action_name="get_quality_monitor_refresh")


class DatabricksCreateOnlineTableConfig(BaseModel):
    """Create an online table (serving-optimized read replica of a UC table)."""
    operation: Literal["create_online_table"] = Field(
        "create_online_table",
        json_schema_extra={"const": "create_online_table", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Create Online Table"},
        title="Create Online Table",
    )
    name: str = Field(..., title="Online Table Name", description="Full three-level name of the online table to create (catalog.schema.table).")
    online_table_json: str = Field("{}", title="Online Table Spec (JSON)", description="The spec object: source_table_full_name, primary_key_columns, run_triggered/run_continuously, timeseries_key, etc.",
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_online_table(c, host, token) -> Dict[str, Any]:
    spec = _parse_json_field(c.online_table_json, "Online Table Spec") or {}
    body = {"name": c.name, "spec": spec}
    return await _databricks_request(host, token, "POST", f"/api/2.0/online-tables", json_body=body, action_name="create_online_table")


class DatabricksGetOnlineTableConfig(BaseModel):
    """Get an online table by name."""
    operation: Literal["get_online_table"] = Field(
        "get_online_table",
        json_schema_extra={"const": "get_online_table", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Get Online Table"},
        title="Get Online Table",
    )
    name: str = Field(..., title="Online Table Name", description="Full three-level name of the online table (catalog.schema.table).")


async def _get_online_table(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/online-tables/{c.name}", action_name="get_online_table")


class DatabricksDeleteOnlineTableConfig(BaseModel):
    """Delete an online table by name."""
    operation: Literal["delete_online_table"] = Field(
        "delete_online_table",
        json_schema_extra={"const": "delete_online_table", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Delete Online Table"},
        title="Delete Online Table",
    )
    name: str = Field(..., title="Online Table Name", description="Full three-level name of the online table to delete (catalog.schema.table).")


async def _delete_online_table(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/online-tables/{c.name}", action_name="delete_online_table")


class DatabricksGetTableLineageConfig(BaseModel):
    """Get upstream and downstream table lineage for a table."""
    operation: Literal["get_table_lineage"] = Field(
        "get_table_lineage",
        json_schema_extra={"const": "get_table_lineage", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Get Table Lineage"},
        title="Get Table Lineage",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the table (catalog.schema.table).")
    include_entity_lineage: str = Field("false", title="Include Entity Lineage", description="Whether to include entity lineage (notebooks, jobs, pipelines) in the response.",
                                        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


async def _get_table_lineage(c, host, token) -> Dict[str, Any]:
    body = {"table_name": c.table_name, "include_entity_lineage": c.include_entity_lineage == "true"}
    return await _databricks_request(host, token, "POST", f"/api/2.0/lineage-tracking/table-lineage", json_body=body, action_name="get_table_lineage")


class DatabricksGetColumnLineageConfig(BaseModel):
    """Get upstream and downstream column lineage for a table column."""
    operation: Literal["get_column_lineage"] = Field(
        "get_column_lineage",
        json_schema_extra={"const": "get_column_lineage", "ui:hidden": True,
                           "x-category": "Unity Catalog Monitoring", "x-is-trigger": False,
                           "x-display-name": "Get Column Lineage"},
        title="Get Column Lineage",
    )
    table_name: str = Field(..., title="Table Name", description="Full three-level name of the table (catalog.schema.table).")
    column_name: str = Field(..., title="Column Name", description="Name of the column to trace lineage for.")


async def _get_column_lineage(c, host, token) -> Dict[str, Any]:
    body = {"table_name": c.table_name, "column_name": c.column_name}
    return await _databricks_request(host, token, "POST", f"/api/2.0/lineage-tracking/column-lineage", json_body=body, action_name="get_column_lineage")


OPERATION_CONFIGS.extend([
    DatabricksCreateQualityMonitorConfig,
    DatabricksGetQualityMonitorConfig,
    DatabricksUpdateQualityMonitorConfig,
    DatabricksDeleteQualityMonitorConfig,
    DatabricksRunQualityMonitorRefreshConfig,
    DatabricksListQualityMonitorRefreshesConfig,
    DatabricksGetQualityMonitorRefreshConfig,
    DatabricksCreateOnlineTableConfig,
    DatabricksGetOnlineTableConfig,
    DatabricksDeleteOnlineTableConfig,
    DatabricksGetTableLineageConfig,
    DatabricksGetColumnLineageConfig,
])
OPERATION_HANDLERS.update({
    "create_quality_monitor": _create_quality_monitor,
    "get_quality_monitor": _get_quality_monitor,
    "update_quality_monitor": _update_quality_monitor,
    "delete_quality_monitor": _delete_quality_monitor,
    "run_quality_monitor_refresh": _run_quality_monitor_refresh,
    "list_quality_monitor_refreshes": _list_quality_monitor_refreshes,
    "get_quality_monitor_refresh": _get_quality_monitor_refresh,
    "create_online_table": _create_online_table,
    "get_online_table": _get_online_table,
    "delete_online_table": _delete_online_table,
    "get_table_lineage": _get_table_lineage,
    "get_column_lineage": _get_column_lineage,
})


# ---- Workspace (13 ops) ----
class DatabricksGetWorkspaceStatusConfig(BaseModel):
    """Get the status of an object or directory in the workspace."""
    operation: Literal["get_workspace_status"] = Field(
        "get_workspace_status",
        json_schema_extra={"const": "get_workspace_status", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Get Workspace Status"},
        title="Get Workspace Status",
    )
    path: str = Field(..., title="Path", description="The absolute path of the notebook or directory, e.g. /Users/me@example.com/project.")


async def _get_workspace_status(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/workspace/get-status", params={"path": c.path}, action_name="get_workspace_status")


class DatabricksDeleteWorkspaceObjectConfig(BaseModel):
    """Delete an object or directory in the workspace."""
    operation: Literal["delete_workspace_object"] = Field(
        "delete_workspace_object",
        json_schema_extra={"const": "delete_workspace_object", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Delete Workspace Object"},
        title="Delete Workspace Object",
    )
    path: str = Field(..., title="Path", description="The absolute path of the notebook or directory to delete.")
    recursive: str = Field(
        "false",
        title="Recursive",
        description="Delete the contents of a directory recursively.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _delete_workspace_object(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/workspace/delete", json_body={"path": c.path, "recursive": c.recursive == "true"}, action_name="delete_workspace_object")


class DatabricksMakeWorkspaceDirectoriesConfig(BaseModel):
    """Create the given directory and necessary parent directories in the workspace."""
    operation: Literal["make_workspace_directories"] = Field(
        "make_workspace_directories",
        json_schema_extra={"const": "make_workspace_directories", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Make Workspace Directories"},
        title="Make Workspace Directories",
    )
    path: str = Field(..., title="Path", description="The absolute path of the directory to create, e.g. /Users/me@example.com/project.")


async def _make_workspace_directories(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/workspace/mkdirs", json_body={"path": c.path}, action_name="make_workspace_directories")


class DatabricksListReposConfig(BaseModel):
    """Get repos that the calling user has Manage permissions on."""
    operation: Literal["list_repos"] = Field(
        "list_repos",
        json_schema_extra={"const": "list_repos", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "List Repos"},
        title="List Repos",
    )
    path_prefix: Optional[str] = Field(None, title="Path Prefix", description="Filter repos that have paths starting with the given path prefix.")
    next_page_token: Optional[str] = Field(None, title="Next Page Token", description="Token to retrieve the next page of results.")


async def _list_repos(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/repos", params={"path_prefix": c.path_prefix, "next_page_token": c.next_page_token}, action_name="list_repos")


class DatabricksCreateRepoConfig(BaseModel):
    """Create a repo in the workspace and link it to a remote Git repo."""
    operation: Literal["create_repo"] = Field(
        "create_repo",
        json_schema_extra={"const": "create_repo", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Create Repo"},
        title="Create Repo",
    )
    url: str = Field(..., title="Git URL", description="URL of the Git repository to be linked.")
    provider: str = Field(..., title="Git Provider", description="Git provider, e.g. gitHub, gitLab, bitbucketCloud, azureDevOpsServices.")
    path: Optional[str] = Field(None, title="Path", description="Desired path for the repo in the workspace, e.g. /Repos/me@example.com/myrepo.")
    sparse_checkout_json: str = Field(
        "{}",
        title="Sparse Checkout (JSON)",
        description="Sparse checkout spec, e.g. {\"patterns\": [\"folder1\", \"folder2\"]}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_repo(c, host, token) -> Dict[str, Any]:
    sparse = _parse_json_field(c.sparse_checkout_json, "Sparse Checkout")
    return await _databricks_request(host, token, "POST", "/api/2.0/repos", json_body={"url": c.url, "provider": c.provider, "path": c.path, "sparse_checkout": sparse or None}, action_name="create_repo")


class DatabricksGetRepoConfig(BaseModel):
    """Get the repo with the given repo ID."""
    operation: Literal["get_repo"] = Field(
        "get_repo",
        json_schema_extra={"const": "get_repo", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Get Repo"},
        title="Get Repo",
    )
    repo_id: str = Field(..., title="Repo ID", description="The ID of the repo to retrieve.")


async def _get_repo(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/repos/{c.repo_id}", action_name="get_repo")


class DatabricksUpdateRepoConfig(BaseModel):
    """Update the repo to a different branch or tag, or update its sparse checkout settings."""
    operation: Literal["update_repo"] = Field(
        "update_repo",
        json_schema_extra={"const": "update_repo", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Update Repo"},
        title="Update Repo",
    )
    repo_id: str = Field(..., title="Repo ID", description="The ID of the repo to update.")
    branch: Optional[str] = Field(None, title="Branch", description="Branch that the local version of the repo is checked out to.")
    tag: Optional[str] = Field(None, title="Tag", description="Tag that the local version of the repo is checked out to.")
    sparse_checkout_json: str = Field(
        "{}",
        title="Sparse Checkout (JSON)",
        description="Sparse checkout spec to update, e.g. {\"patterns\": [\"folder1\"]}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_repo(c, host, token) -> Dict[str, Any]:
    sparse = _parse_json_field(c.sparse_checkout_json, "Sparse Checkout")
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/repos/{c.repo_id}", json_body={"branch": c.branch, "tag": c.tag, "sparse_checkout": sparse or None}, action_name="update_repo")


class DatabricksDeleteRepoConfig(BaseModel):
    """Delete the repo with the given repo ID."""
    operation: Literal["delete_repo"] = Field(
        "delete_repo",
        json_schema_extra={"const": "delete_repo", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Delete Repo"},
        title="Delete Repo",
    )
    repo_id: str = Field(..., title="Repo ID", description="The ID of the repo to delete.")


async def _delete_repo(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/repos/{c.repo_id}", action_name="delete_repo")


class DatabricksListGitCredentialsConfig(BaseModel):
    """Get the calling user's Git credentials."""
    operation: Literal["list_git_credentials"] = Field(
        "list_git_credentials",
        json_schema_extra={"const": "list_git_credentials", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "List Git Credentials"},
        title="List Git Credentials",
    )


async def _list_git_credentials(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/git-credentials", action_name="list_git_credentials")


class DatabricksCreateGitCredentialConfig(BaseModel):
    """Create a Git credential entry for the calling user."""
    operation: Literal["create_git_credential"] = Field(
        "create_git_credential",
        json_schema_extra={"const": "create_git_credential", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Create Git Credential"},
        title="Create Git Credential",
    )
    git_provider: str = Field(..., title="Git Provider", description="Git provider, e.g. gitHub, gitLab, bitbucketCloud, azureDevOpsServices.")
    git_username: Optional[str] = Field(None, title="Git Username", description="Git username for the credential.")
    personal_access_token: Optional[str] = Field(None, title="Personal Access Token", description="The personal access token used to authenticate to the Git provider.")


async def _create_git_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/git-credentials", json_body={"git_provider": c.git_provider, "git_username": c.git_username, "personal_access_token": c.personal_access_token}, action_name="create_git_credential")


class DatabricksGetGitCredentialConfig(BaseModel):
    """Get the Git credential with the given credential ID."""
    operation: Literal["get_git_credential"] = Field(
        "get_git_credential",
        json_schema_extra={"const": "get_git_credential", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Get Git Credential"},
        title="Get Git Credential",
    )
    credential_id: str = Field(..., title="Credential ID", description="The ID of the Git credential to retrieve.")


async def _get_git_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/git-credentials/{c.credential_id}", action_name="get_git_credential")


class DatabricksUpdateGitCredentialConfig(BaseModel):
    """Update the Git credential with the given credential ID."""
    operation: Literal["update_git_credential"] = Field(
        "update_git_credential",
        json_schema_extra={"const": "update_git_credential", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Update Git Credential"},
        title="Update Git Credential",
    )
    credential_id: str = Field(..., title="Credential ID", description="The ID of the Git credential to update.")
    git_provider: Optional[str] = Field(None, title="Git Provider", description="Git provider, e.g. gitHub, gitLab, bitbucketCloud, azureDevOpsServices.")
    git_username: Optional[str] = Field(None, title="Git Username", description="Git username for the credential.")
    personal_access_token: Optional[str] = Field(None, title="Personal Access Token", description="The personal access token used to authenticate to the Git provider.")


async def _update_git_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/git-credentials/{c.credential_id}", json_body={"git_provider": c.git_provider, "git_username": c.git_username, "personal_access_token": c.personal_access_token}, action_name="update_git_credential")


class DatabricksDeleteGitCredentialConfig(BaseModel):
    """Delete the Git credential with the given credential ID."""
    operation: Literal["delete_git_credential"] = Field(
        "delete_git_credential",
        json_schema_extra={"const": "delete_git_credential", "ui:hidden": True,
                           "x-category": "Workspace", "x-is-trigger": False,
                           "x-display-name": "Delete Git Credential"},
        title="Delete Git Credential",
    )
    credential_id: str = Field(..., title="Credential ID", description="The ID of the Git credential to delete.")


async def _delete_git_credential(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/git-credentials/{c.credential_id}", action_name="delete_git_credential")


OPERATION_CONFIGS.extend([
    DatabricksGetWorkspaceStatusConfig,
    DatabricksDeleteWorkspaceObjectConfig,
    DatabricksMakeWorkspaceDirectoriesConfig,
    DatabricksListReposConfig,
    DatabricksCreateRepoConfig,
    DatabricksGetRepoConfig,
    DatabricksUpdateRepoConfig,
    DatabricksDeleteRepoConfig,
    DatabricksListGitCredentialsConfig,
    DatabricksCreateGitCredentialConfig,
    DatabricksGetGitCredentialConfig,
    DatabricksUpdateGitCredentialConfig,
    DatabricksDeleteGitCredentialConfig,
])
OPERATION_HANDLERS.update({
    "get_workspace_status": _get_workspace_status,
    "delete_workspace_object": _delete_workspace_object,
    "make_workspace_directories": _make_workspace_directories,
    "list_repos": _list_repos,
    "create_repo": _create_repo,
    "get_repo": _get_repo,
    "update_repo": _update_repo,
    "delete_repo": _delete_repo,
    "list_git_credentials": _list_git_credentials,
    "create_git_credential": _create_git_credential,
    "get_git_credential": _get_git_credential,
    "update_git_credential": _update_git_credential,
    "delete_git_credential": _delete_git_credential,
})


# ---- Files (17 ops) ----
class DatabricksDbfsListConfig(BaseModel):
    """List the contents of a DBFS directory."""
    operation: Literal["dbfs_list"] = Field(
        "dbfs_list",
        json_schema_extra={"const": "dbfs_list", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: List Directory"},
        title="DBFS: List Directory",
    )
    path: str = Field(..., title="Path", description="The DBFS path to list, e.g. /FileStore or dbfs:/mnt/data")


class DatabricksDbfsGetStatusConfig(BaseModel):
    """Get the file information (status) of a DBFS file or directory."""
    operation: Literal["dbfs_get_status"] = Field(
        "dbfs_get_status",
        json_schema_extra={"const": "dbfs_get_status", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Get Status"},
        title="DBFS: Get Status",
    )
    path: str = Field(..., title="Path", description="The DBFS path to inspect, e.g. /FileStore/data.csv")


class DatabricksDbfsMkdirsConfig(BaseModel):
    """Create the given directory (and necessary parents) in DBFS."""
    operation: Literal["dbfs_mkdirs"] = Field(
        "dbfs_mkdirs",
        json_schema_extra={"const": "dbfs_mkdirs", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Make Directories"},
        title="DBFS: Make Directories",
    )
    path: str = Field(..., title="Path", description="The DBFS directory path to create, e.g. /FileStore/new-folder")


class DatabricksDbfsDeleteConfig(BaseModel):
    """Delete a file or directory from DBFS."""
    operation: Literal["dbfs_delete"] = Field(
        "dbfs_delete",
        json_schema_extra={"const": "dbfs_delete", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Delete"},
        title="DBFS: Delete",
    )
    path: str = Field(..., title="Path", description="The DBFS path to delete, e.g. /FileStore/old-folder")
    recursive: str = Field(
        "false", title="Recursive",
        description="Recursively delete the contents of a directory.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class DatabricksDbfsMoveConfig(BaseModel):
    """Move a file or directory from one DBFS location to another."""
    operation: Literal["dbfs_move"] = Field(
        "dbfs_move",
        json_schema_extra={"const": "dbfs_move", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Move"},
        title="DBFS: Move",
    )
    source_path: str = Field(..., title="Source Path", description="The source DBFS path, e.g. /FileStore/a.csv")
    destination_path: str = Field(..., title="Destination Path", description="The destination DBFS path, e.g. /FileStore/b.csv")


class DatabricksDbfsPutConfig(BaseModel):
    """Upload a small file (<= 1 MB) to DBFS in a single request."""
    operation: Literal["dbfs_put"] = Field(
        "dbfs_put",
        json_schema_extra={"const": "dbfs_put", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Put File"},
        title="DBFS: Put File",
    )
    path: str = Field(..., title="Path", description="The DBFS destination path, e.g. /FileStore/data.txt")
    contents: Optional[str] = Field(
        None, title="Contents (base64)",
        description="Base64-encoded file contents (max 1 MB). Leave empty to create an empty file.",
    )
    overwrite: str = Field(
        "false", title="Overwrite",
        description="Overwrite the file if it already exists.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class DatabricksDbfsReadConfig(BaseModel):
    """Read the contents of a DBFS file, returned base64-encoded."""
    operation: Literal["dbfs_read"] = Field(
        "dbfs_read",
        json_schema_extra={"const": "dbfs_read", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Read File"},
        title="DBFS: Read File",
    )
    path: str = Field(..., title="Path", description="The DBFS path to read, e.g. /FileStore/data.txt")
    offset: Optional[str] = Field(None, title="Offset", description="Byte offset to read from (default 0).")
    length: Optional[str] = Field(None, title="Length", description="Number of bytes to read (max 1 MB per request).")


class DatabricksDbfsCreateConfig(BaseModel):
    """Open a stream to write a file to DBFS, returning an upload handle."""
    operation: Literal["dbfs_create"] = Field(
        "dbfs_create",
        json_schema_extra={"const": "dbfs_create", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Create Upload Handle"},
        title="DBFS: Create Upload Handle",
    )
    path: str = Field(..., title="Path", description="The DBFS destination path for the streamed upload.")
    overwrite: str = Field(
        "false", title="Overwrite",
        description="Overwrite the file if it already exists.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class DatabricksDbfsAddBlockConfig(BaseModel):
    """Append a block of base64-encoded data to an open DBFS upload stream."""
    operation: Literal["dbfs_add_block"] = Field(
        "dbfs_add_block",
        json_schema_extra={"const": "dbfs_add_block", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Add Block"},
        title="DBFS: Add Block",
    )
    handle: str = Field(..., title="Handle", description="The upload handle returned by DBFS: Create Upload Handle.")
    data: str = Field(..., title="Data (base64)", description="Base64-encoded block of data to append (max 1 MB).")


class DatabricksDbfsCloseConfig(BaseModel):
    """Close an open DBFS upload stream, committing the written blocks."""
    operation: Literal["dbfs_close"] = Field(
        "dbfs_close",
        json_schema_extra={"const": "dbfs_close", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "DBFS: Close Upload Handle"},
        title="DBFS: Close Upload Handle",
    )
    handle: str = Field(..., title="Handle", description="The upload handle to close.")


class DatabricksUploadFileConfig(BaseModel):
    """Upload a file to a Unity Catalog volume via the Files API (raw content)."""
    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={"const": "upload_file", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Upload File"},
        title="Files: Upload File",
    )
    file_path: str = Field(
        ..., title="File Path",
        description="Absolute file path starting with a slash, e.g. /Volumes/catalog/schema/volume/file.txt",
    )
    content: str = Field(..., title="Content", description="The raw file content to upload.")
    overwrite: str = Field(
        "false", title="Overwrite",
        description="Overwrite the file if it already exists.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class DatabricksDownloadFileConfig(BaseModel):
    """Download a file from a Unity Catalog volume via the Files API."""
    operation: Literal["download_file"] = Field(
        "download_file",
        json_schema_extra={"const": "download_file", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Download File"},
        title="Files: Download File",
    )
    file_path: str = Field(
        ..., title="File Path",
        description="Absolute file path starting with a slash, e.g. /Volumes/catalog/schema/volume/file.txt",
    )


class DatabricksGetFileMetadataConfig(BaseModel):
    """Get metadata (existence, size, content type) of a Files API file."""
    operation: Literal["get_file_metadata"] = Field(
        "get_file_metadata",
        json_schema_extra={"const": "get_file_metadata", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Get File Metadata"},
        title="Files: Get File Metadata",
    )
    file_path: str = Field(
        ..., title="File Path",
        description="Absolute file path starting with a slash, e.g. /Volumes/catalog/schema/volume/file.txt",
    )


class DatabricksDeleteFileConfig(BaseModel):
    """Delete a file from a Unity Catalog volume via the Files API."""
    operation: Literal["delete_file"] = Field(
        "delete_file",
        json_schema_extra={"const": "delete_file", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Delete File"},
        title="Files: Delete File",
    )
    file_path: str = Field(
        ..., title="File Path",
        description="Absolute file path starting with a slash, e.g. /Volumes/catalog/schema/volume/file.txt",
    )


class DatabricksCreateDirectoryConfig(BaseModel):
    """Create a directory (and necessary parents) in a Unity Catalog volume."""
    operation: Literal["create_directory"] = Field(
        "create_directory",
        json_schema_extra={"const": "create_directory", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Create Directory"},
        title="Files: Create Directory",
    )
    directory_path: str = Field(
        ..., title="Directory Path",
        description="Absolute directory path starting with a slash, e.g. /Volumes/catalog/schema/volume/subdir",
    )


class DatabricksListDirectoryContentsConfig(BaseModel):
    """List the contents of a directory in a Unity Catalog volume."""
    operation: Literal["list_directory_contents"] = Field(
        "list_directory_contents",
        json_schema_extra={"const": "list_directory_contents", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: List Directory Contents"},
        title="Files: List Directory Contents",
    )
    directory_path: str = Field(
        ..., title="Directory Path",
        description="Absolute directory path starting with a slash, e.g. /Volumes/catalog/schema/volume/subdir",
    )
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token from a previous response.")


class DatabricksDeleteDirectoryConfig(BaseModel):
    """Delete an (empty) directory from a Unity Catalog volume."""
    operation: Literal["delete_directory"] = Field(
        "delete_directory",
        json_schema_extra={"const": "delete_directory", "ui:hidden": True,
                           "x-category": "Files", "x-is-trigger": False,
                           "x-display-name": "Files: Delete Directory"},
        title="Files: Delete Directory",
    )
    directory_path: str = Field(
        ..., title="Directory Path",
        description="Absolute directory path starting with a slash, e.g. /Volumes/catalog/schema/volume/subdir",
    )


async def _dbfs_list(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/dbfs/list", params={"path": c.path}, action_name="dbfs_list"
    )


async def _dbfs_get_status(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/dbfs/get-status", params={"path": c.path}, action_name="dbfs_get_status"
    )


async def _dbfs_mkdirs(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/mkdirs", json_body={"path": c.path}, action_name="dbfs_mkdirs"
    )


async def _dbfs_delete(c, host, token) -> Dict[str, Any]:
    body = {"path": c.path, "recursive": c.recursive == "true"}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/delete", json_body=body, action_name="dbfs_delete"
    )


async def _dbfs_move(c, host, token) -> Dict[str, Any]:
    body = {"source_path": c.source_path, "destination_path": c.destination_path}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/move", json_body=body, action_name="dbfs_move"
    )


async def _dbfs_put(c, host, token) -> Dict[str, Any]:
    body = {"path": c.path, "contents": c.contents, "overwrite": c.overwrite == "true"}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/put", json_body=body, action_name="dbfs_put"
    )


async def _dbfs_read(c, host, token) -> Dict[str, Any]:
    params = {"path": c.path, "offset": c.offset, "length": c.length}
    return await _databricks_request(
        host, token, "GET", "/api/2.0/dbfs/read", params=params, action_name="dbfs_read"
    )


async def _dbfs_create(c, host, token) -> Dict[str, Any]:
    body = {"path": c.path, "overwrite": c.overwrite == "true"}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/create", json_body=body, action_name="dbfs_create"
    )


async def _dbfs_add_block(c, host, token) -> Dict[str, Any]:
    handle = int(c.handle) if str(c.handle).isdigit() else c.handle
    body = {"handle": handle, "data": c.data}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/add-block", json_body=body, action_name="dbfs_add_block"
    )


async def _dbfs_close(c, host, token) -> Dict[str, Any]:
    handle = int(c.handle) if str(c.handle).isdigit() else c.handle
    return await _databricks_request(
        host, token, "POST", "/api/2.0/dbfs/close", json_body={"handle": handle}, action_name="dbfs_close"
    )


async def _upload_file(c, host, token) -> Dict[str, Any]:
    params = {"overwrite": "true" if c.overwrite == "true" else "false"}
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/fs/files{c.file_path}", params=params,
        data=c.content, content_type="application/octet-stream", action_name="upload_file"
    )


async def _download_file(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/fs/files{c.file_path}", action_name="download_file"
    )


async def _get_file_metadata(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "HEAD", f"/api/2.0/fs/files{c.file_path}", action_name="get_file_metadata"
    )


async def _delete_file(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/fs/files{c.file_path}", action_name="delete_file"
    )


async def _create_directory(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/fs/directories{c.directory_path}", action_name="create_directory"
    )


async def _list_directory_contents(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/fs/directories{c.directory_path}",
        params={"page_token": c.page_token}, action_name="list_directory_contents"
    )


async def _delete_directory(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/fs/directories{c.directory_path}", action_name="delete_directory"
    )


OPERATION_CONFIGS.extend([
    DatabricksDbfsListConfig,
    DatabricksDbfsGetStatusConfig,
    DatabricksDbfsMkdirsConfig,
    DatabricksDbfsDeleteConfig,
    DatabricksDbfsMoveConfig,
    DatabricksDbfsPutConfig,
    DatabricksDbfsReadConfig,
    DatabricksDbfsCreateConfig,
    DatabricksDbfsAddBlockConfig,
    DatabricksDbfsCloseConfig,
    DatabricksUploadFileConfig,
    DatabricksDownloadFileConfig,
    DatabricksGetFileMetadataConfig,
    DatabricksDeleteFileConfig,
    DatabricksCreateDirectoryConfig,
    DatabricksListDirectoryContentsConfig,
    DatabricksDeleteDirectoryConfig,
])
OPERATION_HANDLERS.update({
    "dbfs_list": _dbfs_list,
    "dbfs_get_status": _dbfs_get_status,
    "dbfs_mkdirs": _dbfs_mkdirs,
    "dbfs_delete": _dbfs_delete,
    "dbfs_move": _dbfs_move,
    "dbfs_put": _dbfs_put,
    "dbfs_read": _dbfs_read,
    "dbfs_create": _dbfs_create,
    "dbfs_add_block": _dbfs_add_block,
    "dbfs_close": _dbfs_close,
    "upload_file": _upload_file,
    "download_file": _download_file,
    "get_file_metadata": _get_file_metadata,
    "delete_file": _delete_file,
    "create_directory": _create_directory,
    "list_directory_contents": _list_directory_contents,
    "delete_directory": _delete_directory,
})


# ---- Secrets (10 ops) ----
class DatabricksCreateSecretScopeConfig(BaseModel):
    """Create a Databricks-backed or Azure Key Vault-backed secret scope."""
    operation: Literal["create_secret_scope"] = Field(
        "create_secret_scope",
        json_schema_extra={"const": "create_secret_scope", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Create Secret Scope"},
        title="Create Secret Scope",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the secret scope to create (must be unique within the workspace).")
    initial_manage_principal: Optional[str] = Field(None, title="Initial Manage Principal", description="Principal initially granted MANAGE permission. Set to 'users' to grant all workspace users access.")
    scope_backend_type: Optional[str] = Field(None, title="Backend Type", description="Backend for the scope. DATABRICKS (default) or AZURE_KEYVAULT.",
        json_schema_extra={"enum": ["DATABRICKS", "AZURE_KEYVAULT"], "enumNames": ["Databricks", "Azure Key Vault"], "x-enum-searchable": True})
    backend_azure_keyvault_json: str = Field("{}", title="Azure Key Vault Backend (JSON)", description="Azure Key Vault metadata: e.g. {\"resource_id\": \"...\", \"dns_name\": \"...\"}. Required when Backend Type is AZURE_KEYVAULT.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_secret_scope(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "scope": c.scope,
        "initial_manage_principal": c.initial_manage_principal,
        "scope_backend_type": c.scope_backend_type,
    }
    keyvault = _parse_json_field(c.backend_azure_keyvault_json, "Azure Key Vault Backend")
    if keyvault:
        body["backend_azure_keyvault"] = keyvault
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/scopes/create", json_body=body, action_name="create_secret_scope")


class DatabricksDeleteSecretScopeConfig(BaseModel):
    """Delete a secret scope."""
    operation: Literal["delete_secret_scope"] = Field(
        "delete_secret_scope",
        json_schema_extra={"const": "delete_secret_scope", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Delete Secret Scope"},
        title="Delete Secret Scope",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the secret scope to delete.")


async def _delete_secret_scope(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/scopes/delete", json_body={"scope": c.scope}, action_name="delete_secret_scope")


class DatabricksPutSecretConfig(BaseModel):
    """Insert or update a secret in a scope."""
    operation: Literal["put_secret"] = Field(
        "put_secret",
        json_schema_extra={"const": "put_secret", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Put Secret"},
        title="Put Secret",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope to store the secret in.")
    key: str = Field(..., title="Secret Key", description="Unique name identifying the secret within the scope.")
    string_value: Optional[str] = Field(None, title="String Value", description="Secret value as a UTF-8 string. Provide either this or Bytes Value.")
    bytes_value: Optional[str] = Field(None, title="Bytes Value", description="Secret value as base64-encoded bytes. Provide either this or String Value.")


async def _put_secret(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/put", json_body={
        "scope": c.scope,
        "key": c.key,
        "string_value": c.string_value,
        "bytes_value": c.bytes_value,
    }, action_name="put_secret")


class DatabricksDeleteSecretConfig(BaseModel):
    """Delete a secret from a scope."""
    operation: Literal["delete_secret"] = Field(
        "delete_secret",
        json_schema_extra={"const": "delete_secret", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Delete Secret"},
        title="Delete Secret",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope containing the secret.")
    key: str = Field(..., title="Secret Key", description="Name of the secret to delete.")


async def _delete_secret(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/delete", json_body={"scope": c.scope, "key": c.key}, action_name="delete_secret")


class DatabricksGetSecretConfig(BaseModel):
    """Get the bytes value of a secret."""
    operation: Literal["get_secret"] = Field(
        "get_secret",
        json_schema_extra={"const": "get_secret", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Get Secret"},
        title="Get Secret",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope containing the secret.")
    key: str = Field(..., title="Secret Key", description="Name of the secret to fetch. Value is returned base64-encoded.")


async def _get_secret(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/secrets/get", params={"scope": c.scope, "key": c.key}, action_name="get_secret")


class DatabricksListSecretsConfig(BaseModel):
    """List secret metadata (keys and timestamps) for a scope."""
    operation: Literal["list_secrets"] = Field(
        "list_secrets",
        json_schema_extra={"const": "list_secrets", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "List Secrets"},
        title="List Secrets",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope whose secret metadata to list.")


async def _list_secrets(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/secrets/list", params={"scope": c.scope}, action_name="list_secrets")


class DatabricksPutSecretAclConfig(BaseModel):
    """Create or overwrite an ACL on a secret scope for a principal."""
    operation: Literal["put_secret_acl"] = Field(
        "put_secret_acl",
        json_schema_extra={"const": "put_secret_acl", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Put Secret ACL"},
        title="Put Secret ACL",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope to apply the ACL to.")
    principal: str = Field(..., title="Principal", description="User, group, or service principal to grant the permission to.")
    permission: str = Field(..., title="Permission", description="Permission level to grant.",
        json_schema_extra={"enum": ["READ", "WRITE", "MANAGE"], "enumNames": ["Read", "Write", "Manage"], "x-enum-searchable": True})


async def _put_secret_acl(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/acls/put", json_body={
        "scope": c.scope,
        "principal": c.principal,
        "permission": c.permission,
    }, action_name="put_secret_acl")


class DatabricksDeleteSecretAclConfig(BaseModel):
    """Delete an ACL on a secret scope for a principal."""
    operation: Literal["delete_secret_acl"] = Field(
        "delete_secret_acl",
        json_schema_extra={"const": "delete_secret_acl", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Delete Secret ACL"},
        title="Delete Secret ACL",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope the ACL belongs to.")
    principal: str = Field(..., title="Principal", description="Principal whose ACL should be removed.")


async def _delete_secret_acl(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/secrets/acls/delete", json_body={"scope": c.scope, "principal": c.principal}, action_name="delete_secret_acl")


class DatabricksGetSecretAclConfig(BaseModel):
    """Get the ACL applied to a principal for a secret scope."""
    operation: Literal["get_secret_acl"] = Field(
        "get_secret_acl",
        json_schema_extra={"const": "get_secret_acl", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "Get Secret ACL"},
        title="Get Secret ACL",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope the ACL belongs to.")
    principal: str = Field(..., title="Principal", description="Principal whose ACL to fetch.")


async def _get_secret_acl(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/secrets/acls/get", params={"scope": c.scope, "principal": c.principal}, action_name="get_secret_acl")


class DatabricksListSecretAclsConfig(BaseModel):
    """List all ACLs applied to a secret scope."""
    operation: Literal["list_secret_acls"] = Field(
        "list_secret_acls",
        json_schema_extra={"const": "list_secret_acls", "ui:hidden": True,
                           "x-category": "Secrets", "x-is-trigger": False,
                           "x-display-name": "List Secret ACLs"},
        title="List Secret ACLs",
    )
    scope: str = Field(..., title="Scope Name", description="Name of the scope whose ACLs to list.")


async def _list_secret_acls(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/secrets/acls/list", params={"scope": c.scope}, action_name="list_secret_acls")


OPERATION_CONFIGS.extend([
    DatabricksCreateSecretScopeConfig,
    DatabricksDeleteSecretScopeConfig,
    DatabricksPutSecretConfig,
    DatabricksDeleteSecretConfig,
    DatabricksGetSecretConfig,
    DatabricksListSecretsConfig,
    DatabricksPutSecretAclConfig,
    DatabricksDeleteSecretAclConfig,
    DatabricksGetSecretAclConfig,
    DatabricksListSecretAclsConfig,
])
OPERATION_HANDLERS.update({
    "create_secret_scope": _create_secret_scope,
    "delete_secret_scope": _delete_secret_scope,
    "put_secret": _put_secret,
    "delete_secret": _delete_secret,
    "get_secret": _get_secret,
    "list_secrets": _list_secrets,
    "put_secret_acl": _put_secret_acl,
    "delete_secret_acl": _delete_secret_acl,
    "get_secret_acl": _get_secret_acl,
    "list_secret_acls": _list_secret_acls,
})


# ---- Pipelines (10 ops) ----
class DatabricksListPipelinesConfig(BaseModel):
    """List Delta Live Tables pipelines in the workspace."""
    operation: Literal["list_pipelines"] = Field(
        "list_pipelines",
        json_schema_extra={"const": "list_pipelines", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "List Pipelines"},
        title="List Pipelines",
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Max number of pipelines to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter expression, e.g. name LIKE '%prod%'"
    )
    order_by: Optional[str] = Field(
        None, title="Order By", description="Sort expression, e.g. name ASC or timestamp DESC"
    )


class DatabricksCreatePipelineConfig(BaseModel):
    """Create a new Delta Live Tables pipeline."""
    operation: Literal["create_pipeline"] = Field(
        "create_pipeline",
        json_schema_extra={"const": "create_pipeline", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Create Pipeline"},
        title="Create Pipeline",
    )
    name: str = Field(..., title="Pipeline Name", description="A name for the new pipeline")
    pipeline_json: str = Field(
        "{}",
        title="Pipeline Spec (JSON)",
        description="Full pipeline spec (clusters, libraries, target, continuous, etc). The name field is merged in automatically.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetPipelineConfig(BaseModel):
    """Get a single pipeline's definition and status."""
    operation: Literal["get_pipeline"] = Field(
        "get_pipeline",
        json_schema_extra={"const": "get_pipeline", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Get Pipeline"},
        title="Get Pipeline",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to retrieve")


class DatabricksUpdatePipelineConfig(BaseModel):
    """Update (replace) an existing pipeline's settings."""
    operation: Literal["update_pipeline"] = Field(
        "update_pipeline",
        json_schema_extra={"const": "update_pipeline", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Update Pipeline"},
        title="Update Pipeline",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to update")
    pipeline_json: str = Field(
        "{}",
        title="Pipeline Spec (JSON)",
        description="Full pipeline spec to replace the existing settings with",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeletePipelineConfig(BaseModel):
    """Delete a pipeline."""
    operation: Literal["delete_pipeline"] = Field(
        "delete_pipeline",
        json_schema_extra={"const": "delete_pipeline", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Delete Pipeline"},
        title="Delete Pipeline",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to delete")


class DatabricksStartPipelineUpdateConfig(BaseModel):
    """Trigger a new update (run) of a pipeline."""
    operation: Literal["start_pipeline_update"] = Field(
        "start_pipeline_update",
        json_schema_extra={"const": "start_pipeline_update", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Start Pipeline Update"},
        title="Start Pipeline Update",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to update")
    full_refresh: str = Field(
        "false",
        title="Full Refresh",
        description="Reprocess all data (reset tables) instead of an incremental update",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"],
                           "x-enum-searchable": True},
    )
    refresh_selection_json: Optional[str] = Field(
        None,
        title="Refresh Selection (JSON)",
        description="Optional JSON array of table names to selectively refresh",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    full_refresh_selection_json: Optional[str] = Field(
        None,
        title="Full Refresh Selection (JSON)",
        description="Optional JSON array of table names to selectively full-refresh",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetPipelineUpdateConfig(BaseModel):
    """Get the status of a specific pipeline update."""
    operation: Literal["get_pipeline_update"] = Field(
        "get_pipeline_update",
        json_schema_extra={"const": "get_pipeline_update", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Get Pipeline Update"},
        title="Get Pipeline Update",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline the update belongs to")
    update_id: str = Field(..., title="Update ID", description="The update (run) to retrieve")


class DatabricksListPipelineUpdatesConfig(BaseModel):
    """List updates (runs) for a pipeline."""
    operation: Literal["list_pipeline_updates"] = Field(
        "list_pipeline_updates",
        json_schema_extra={"const": "list_pipeline_updates", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "List Pipeline Updates"},
        title="List Pipeline Updates",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to list updates for")
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Max number of updates to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


class DatabricksStopPipelineConfig(BaseModel):
    """Stop the pipeline's active update if one is running."""
    operation: Literal["stop_pipeline"] = Field(
        "stop_pipeline",
        json_schema_extra={"const": "stop_pipeline", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "Stop Pipeline"},
        title="Stop Pipeline",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline whose update to stop")


class DatabricksListPipelineEventsConfig(BaseModel):
    """List event log entries for a pipeline."""
    operation: Literal["list_pipeline_events"] = Field(
        "list_pipeline_events",
        json_schema_extra={"const": "list_pipeline_events", "ui:hidden": True,
                           "x-category": "Pipelines", "x-is-trigger": False,
                           "x-display-name": "List Pipeline Events"},
        title="List Pipeline Events",
    )
    pipeline_id: str = Field(..., title="Pipeline ID", description="The pipeline to list events for")
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Max number of events to return per page"
    )
    order_by: Optional[str] = Field(
        None, title="Order By", description="Sort expression, e.g. timestamp ASC"
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter expression over event attributes"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


async def _list_pipelines(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/pipelines",
        params={"max_results": c.max_results, "page_token": c.page_token,
                "filter": c.filter, "order_by": c.order_by},
        action_name="list_pipelines",
    )


async def _create_pipeline(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.pipeline_json, "Pipeline Spec") or {}
    body["name"] = c.name
    return await _databricks_request(
        host, token, "POST", "/api/2.0/pipelines", json_body=body, action_name="create_pipeline"
    )


async def _get_pipeline(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/pipelines/{c.pipeline_id}", action_name="get_pipeline"
    )


async def _update_pipeline(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.pipeline_json, "Pipeline Spec") or {}
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/pipelines/{c.pipeline_id}", json_body=body,
        action_name="update_pipeline",
    )


async def _delete_pipeline(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/pipelines/{c.pipeline_id}", action_name="delete_pipeline"
    )


async def _start_pipeline_update(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/pipelines/{c.pipeline_id}/updates",
        json_body={
            "full_refresh": c.full_refresh == "true",
            "refresh_selection": _parse_json_field(c.refresh_selection_json, "Refresh Selection"),
            "full_refresh_selection": _parse_json_field(
                c.full_refresh_selection_json, "Full Refresh Selection"
            ),
        },
        action_name="start_pipeline_update",
    )


async def _get_pipeline_update(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/pipelines/{c.pipeline_id}/updates/{c.update_id}",
        action_name="get_pipeline_update",
    )


async def _list_pipeline_updates(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/pipelines/{c.pipeline_id}/updates",
        params={"max_results": c.max_results, "page_token": c.page_token},
        action_name="list_pipeline_updates",
    )


async def _stop_pipeline(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/pipelines/{c.pipeline_id}/stop", action_name="stop_pipeline"
    )


async def _list_pipeline_events(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/pipelines/{c.pipeline_id}/events",
        params={"max_results": c.max_results, "order_by": c.order_by,
                "filter": c.filter, "page_token": c.page_token},
        action_name="list_pipeline_events",
    )


OPERATION_CONFIGS.extend([
    DatabricksListPipelinesConfig, DatabricksCreatePipelineConfig, DatabricksGetPipelineConfig,
    DatabricksUpdatePipelineConfig, DatabricksDeletePipelineConfig,
    DatabricksStartPipelineUpdateConfig, DatabricksGetPipelineUpdateConfig,
    DatabricksListPipelineUpdatesConfig, DatabricksStopPipelineConfig,
    DatabricksListPipelineEventsConfig,
])
OPERATION_HANDLERS.update({
    "list_pipelines": _list_pipelines,
    "create_pipeline": _create_pipeline,
    "get_pipeline": _get_pipeline,
    "update_pipeline": _update_pipeline,
    "delete_pipeline": _delete_pipeline,
    "start_pipeline_update": _start_pipeline_update,
    "get_pipeline_update": _get_pipeline_update,
    "list_pipeline_updates": _list_pipeline_updates,
    "stop_pipeline": _stop_pipeline,
    "list_pipeline_events": _list_pipeline_events,
})


# ---- Serving Endpoints (10 ops) ----
class DatabricksListServingEndpointsConfig(BaseModel):
    """List all serving endpoints in the workspace."""

    operation: Literal["list_serving_endpoints"] = Field(
        "list_serving_endpoints",
        json_schema_extra={
            "const": "list_serving_endpoints",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "List Serving Endpoints",
        },
        title="List Serving Endpoints",
    )


class DatabricksCreateServingEndpointConfig(BaseModel):
    """Create a new model serving endpoint."""

    operation: Literal["create_serving_endpoint"] = Field(
        "create_serving_endpoint",
        json_schema_extra={
            "const": "create_serving_endpoint",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Create Serving Endpoint",
        },
        title="Create Serving Endpoint",
    )
    name: str = Field(..., title="Endpoint Name", description="A unique name for the serving endpoint")
    config_json: str = Field(
        "{}",
        title="Endpoint Config (JSON)",
        description="JSON object for the endpoint config (served_entities/served_models, traffic_config, tags, etc.)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetServingEndpointConfig(BaseModel):
    """Get details of a serving endpoint by name."""

    operation: Literal["get_serving_endpoint"] = Field(
        "get_serving_endpoint",
        json_schema_extra={
            "const": "get_serving_endpoint",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Get Serving Endpoint",
        },
        title="Get Serving Endpoint",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint")


class DatabricksUpdateServingEndpointConfigConfig(BaseModel):
    """Update the config (served entities and traffic) of a serving endpoint."""

    operation: Literal["update_serving_endpoint_config"] = Field(
        "update_serving_endpoint_config",
        json_schema_extra={
            "const": "update_serving_endpoint_config",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Update Serving Endpoint Config",
        },
        title="Update Serving Endpoint Config",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint to update")
    config_json: str = Field(
        "{}",
        title="Endpoint Config (JSON)",
        description="JSON object with the new config (served_entities/served_models, traffic_config, etc.)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeleteServingEndpointConfig(BaseModel):
    """Delete a serving endpoint by name."""

    operation: Literal["delete_serving_endpoint"] = Field(
        "delete_serving_endpoint",
        json_schema_extra={
            "const": "delete_serving_endpoint",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Delete Serving Endpoint",
        },
        title="Delete Serving Endpoint",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint to delete")


class DatabricksQueryServingEndpointConfig(BaseModel):
    """Query (invoke) a serving endpoint with a request payload."""

    operation: Literal["query_serving_endpoint"] = Field(
        "query_serving_endpoint",
        json_schema_extra={
            "const": "query_serving_endpoint",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Query Serving Endpoint",
        },
        title="Query Serving Endpoint",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint to query")
    payload_json: str = Field(
        "{}",
        title="Request Payload (JSON)",
        description="The full invocation payload (e.g. {\"inputs\": [...]} or {\"messages\": [...]})",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksPatchServingEndpointTagsConfig(BaseModel):
    """Add or remove tags on a serving endpoint."""

    operation: Literal["patch_serving_endpoint_tags"] = Field(
        "patch_serving_endpoint_tags",
        json_schema_extra={
            "const": "patch_serving_endpoint_tags",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Patch Serving Endpoint Tags",
        },
        title="Patch Serving Endpoint Tags",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint")
    add_tags_json: Optional[str] = Field(
        None,
        title="Add Tags (JSON)",
        description="JSON array of tag objects to add, e.g. [{\"key\": \"team\", \"value\": \"ml\"}]",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    delete_tags_json: Optional[str] = Field(
        None,
        title="Delete Tags (JSON)",
        description="JSON array of tag keys to delete, e.g. [\"team\", \"env\"]",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksPutServingEndpointRateLimitsConfig(BaseModel):
    """Set (replace) the rate limits on a serving endpoint."""

    operation: Literal["put_serving_endpoint_rate_limits"] = Field(
        "put_serving_endpoint_rate_limits",
        json_schema_extra={
            "const": "put_serving_endpoint_rate_limits",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Put Serving Endpoint Rate Limits",
        },
        title="Put Serving Endpoint Rate Limits",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint")
    rate_limits_json: str = Field(
        "[]",
        title="Rate Limits (JSON)",
        description="JSON array of rate limit objects, e.g. [{\"calls\": 100, \"key\": \"endpoint\", \"renewal_period\": \"minute\"}]",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetServingEndpointOpenapiConfig(BaseModel):
    """Get the OpenAPI schema of a serving endpoint."""

    operation: Literal["get_serving_endpoint_openapi"] = Field(
        "get_serving_endpoint_openapi",
        json_schema_extra={
            "const": "get_serving_endpoint_openapi",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Get Serving Endpoint OpenAPI",
        },
        title="Get Serving Endpoint OpenAPI",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint")


class DatabricksGetServingEndpointMetricsConfig(BaseModel):
    """Get the metrics of a serving endpoint (Prometheus/OpenMetrics format)."""

    operation: Literal["get_serving_endpoint_metrics"] = Field(
        "get_serving_endpoint_metrics",
        json_schema_extra={
            "const": "get_serving_endpoint_metrics",
            "ui:hidden": True,
            "x-category": "Serving Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Get Serving Endpoint Metrics",
        },
        title="Get Serving Endpoint Metrics",
    )
    name: str = Field(..., title="Endpoint Name", description="The name of the serving endpoint")


async def _list_serving_endpoints(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/serving-endpoints", action_name="list_serving_endpoints"
    )


async def _create_serving_endpoint(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.config_json, "Endpoint Config") or {}
    body["name"] = c.name
    return await _databricks_request(
        host, token, "POST", "/api/2.0/serving-endpoints", json_body=body, action_name="create_serving_endpoint"
    )


async def _get_serving_endpoint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/serving-endpoints/{c.name}", action_name="get_serving_endpoint"
    )


async def _update_serving_endpoint_config(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.config_json, "Endpoint Config") or {}
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/serving-endpoints/{c.name}/config", json_body=body,
        action_name="update_serving_endpoint_config",
    )


async def _delete_serving_endpoint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/serving-endpoints/{c.name}", action_name="delete_serving_endpoint"
    )


async def _query_serving_endpoint(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.payload_json, "Request Payload") or {}
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/serving-endpoints/{c.name}/invocations", json_body=body,
        action_name="query_serving_endpoint",
    )


async def _patch_serving_endpoint_tags(c, host, token) -> Dict[str, Any]:
    body = {
        "add_tags": _parse_json_field(c.add_tags_json, "Add Tags"),
        "delete_tags": _parse_json_field(c.delete_tags_json, "Delete Tags"),
    }
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.0/serving-endpoints/{c.name}/tags", json_body=body,
        action_name="patch_serving_endpoint_tags",
    )


async def _put_serving_endpoint_rate_limits(c, host, token) -> Dict[str, Any]:
    body = {"rate_limits": _parse_json_field(c.rate_limits_json, "Rate Limits")}
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/serving-endpoints/{c.name}/rate-limits", json_body=body,
        action_name="put_serving_endpoint_rate_limits",
    )


async def _get_serving_endpoint_openapi(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/serving-endpoints/{c.name}/openapi",
        action_name="get_serving_endpoint_openapi",
    )


async def _get_serving_endpoint_metrics(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/serving-endpoints/{c.name}/metrics",
        action_name="get_serving_endpoint_metrics",
    )


OPERATION_CONFIGS.extend([
    DatabricksListServingEndpointsConfig,
    DatabricksCreateServingEndpointConfig,
    DatabricksGetServingEndpointConfig,
    DatabricksUpdateServingEndpointConfigConfig,
    DatabricksDeleteServingEndpointConfig,
    DatabricksQueryServingEndpointConfig,
    DatabricksPatchServingEndpointTagsConfig,
    DatabricksPutServingEndpointRateLimitsConfig,
    DatabricksGetServingEndpointOpenapiConfig,
    DatabricksGetServingEndpointMetricsConfig,
])
OPERATION_HANDLERS.update({
    "list_serving_endpoints": _list_serving_endpoints,
    "create_serving_endpoint": _create_serving_endpoint,
    "get_serving_endpoint": _get_serving_endpoint,
    "update_serving_endpoint_config": _update_serving_endpoint_config,
    "delete_serving_endpoint": _delete_serving_endpoint,
    "query_serving_endpoint": _query_serving_endpoint,
    "patch_serving_endpoint_tags": _patch_serving_endpoint_tags,
    "put_serving_endpoint_rate_limits": _put_serving_endpoint_rate_limits,
    "get_serving_endpoint_openapi": _get_serving_endpoint_openapi,
    "get_serving_endpoint_metrics": _get_serving_endpoint_metrics,
})


# ---- Vector Search (14 ops) ----
class DatabricksListVectorSearchEndpointsConfig(BaseModel):
    """List all vector search endpoints in the workspace"""
    operation: Literal["list_vector_search_endpoints"] = Field(
        "list_vector_search_endpoints",
        json_schema_extra={"const": "list_vector_search_endpoints", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "List Vector Search Endpoints"},
        title="List Vector Search Endpoints",
    )
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for pagination to retrieve the next page of results")


async def _list_vector_search_endpoints(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/vector-search/endpoints", params={"page_token": c.page_token}, action_name="list_vector_search_endpoints")


class DatabricksCreateVectorSearchEndpointConfig(BaseModel):
    """Create a new vector search endpoint"""
    operation: Literal["create_vector_search_endpoint"] = Field(
        "create_vector_search_endpoint",
        json_schema_extra={"const": "create_vector_search_endpoint", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Create Vector Search Endpoint"},
        title="Create Vector Search Endpoint",
    )
    name: str = Field(..., title="Endpoint Name", description="Name of the vector search endpoint to create")
    endpoint_type: str = Field(
        "STANDARD", title="Endpoint Type", description="Type of the vector search endpoint",
        json_schema_extra={"enum": ["STANDARD"], "enumNames": ["Standard"], "x-enum-searchable": True},
    )


async def _create_vector_search_endpoint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/vector-search/endpoints", json_body={"name": c.name, "endpoint_type": c.endpoint_type}, action_name="create_vector_search_endpoint")


class DatabricksGetVectorSearchEndpointConfig(BaseModel):
    """Get details of a vector search endpoint"""
    operation: Literal["get_vector_search_endpoint"] = Field(
        "get_vector_search_endpoint",
        json_schema_extra={"const": "get_vector_search_endpoint", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Get Vector Search Endpoint"},
        title="Get Vector Search Endpoint",
    )
    endpoint_name: str = Field(..., title="Endpoint Name", description="Name of the vector search endpoint to retrieve")


async def _get_vector_search_endpoint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/vector-search/endpoints/{c.endpoint_name}", action_name="get_vector_search_endpoint")


class DatabricksDeleteVectorSearchEndpointConfig(BaseModel):
    """Delete a vector search endpoint"""
    operation: Literal["delete_vector_search_endpoint"] = Field(
        "delete_vector_search_endpoint",
        json_schema_extra={"const": "delete_vector_search_endpoint", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Delete Vector Search Endpoint"},
        title="Delete Vector Search Endpoint",
    )
    endpoint_name: str = Field(..., title="Endpoint Name", description="Name of the vector search endpoint to delete")


async def _delete_vector_search_endpoint(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/vector-search/endpoints/{c.endpoint_name}", action_name="delete_vector_search_endpoint")


class DatabricksListVectorSearchIndexesConfig(BaseModel):
    """List all vector search indexes on an endpoint"""
    operation: Literal["list_vector_search_indexes"] = Field(
        "list_vector_search_indexes",
        json_schema_extra={"const": "list_vector_search_indexes", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "List Vector Search Indexes"},
        title="List Vector Search Indexes",
    )
    endpoint_name: str = Field(..., title="Endpoint Name", description="Name of the endpoint whose indexes to list")
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for pagination to retrieve the next page of results")


async def _list_vector_search_indexes(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/vector-search/indexes", params={"endpoint_name": c.endpoint_name, "page_token": c.page_token}, action_name="list_vector_search_indexes")


class DatabricksCreateVectorSearchIndexConfig(BaseModel):
    """Create a new vector search index"""
    operation: Literal["create_vector_search_index"] = Field(
        "create_vector_search_index",
        json_schema_extra={"const": "create_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Create Vector Search Index"},
        title="Create Vector Search Index",
    )
    name: str = Field(..., title="Index Name", description="Three-part name of the index to create (catalog.schema.index)")
    endpoint_name: str = Field(..., title="Endpoint Name", description="Name of the endpoint to create the index on")
    primary_key: str = Field(..., title="Primary Key", description="Primary key column of the index")
    index_type: str = Field(
        "DELTA_SYNC", title="Index Type", description="Type of the vector search index",
        json_schema_extra={"enum": ["DELTA_SYNC", "DIRECT_ACCESS"], "enumNames": ["Delta Sync", "Direct Access"], "x-enum-searchable": True},
    )
    index_json: str = Field(
        "{}", title="Index Spec (JSON)",
        description="JSON object with delta_sync_index_spec or direct_access_index_spec (and any other index fields to merge into the request body)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_vector_search_index(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.index_json, "Index Spec") or {}
    body.update({"name": c.name, "endpoint_name": c.endpoint_name, "primary_key": c.primary_key, "index_type": c.index_type})
    return await _databricks_request(host, token, "POST", "/api/2.0/vector-search/indexes", json_body=body, action_name="create_vector_search_index")


class DatabricksGetVectorSearchIndexConfig(BaseModel):
    """Get details of a vector search index"""
    operation: Literal["get_vector_search_index"] = Field(
        "get_vector_search_index",
        json_schema_extra={"const": "get_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Get Vector Search Index"},
        title="Get Vector Search Index",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to retrieve")


async def _get_vector_search_index(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/vector-search/indexes/{c.index_name}", action_name="get_vector_search_index")


class DatabricksDeleteVectorSearchIndexConfig(BaseModel):
    """Delete a vector search index"""
    operation: Literal["delete_vector_search_index"] = Field(
        "delete_vector_search_index",
        json_schema_extra={"const": "delete_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Delete Vector Search Index"},
        title="Delete Vector Search Index",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to delete")


async def _delete_vector_search_index(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/vector-search/indexes/{c.index_name}", action_name="delete_vector_search_index")


class DatabricksQueryVectorSearchIndexConfig(BaseModel):
    """Query a vector search index"""
    operation: Literal["query_vector_search_index"] = Field(
        "query_vector_search_index",
        json_schema_extra={"const": "query_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Query Vector Search Index"},
        title="Query Vector Search Index",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to query")
    columns_json: str = Field(
        "[]", title="Columns (JSON)", description="JSON array of column names to return in the query results",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    query_text: Optional[str] = Field(None, title="Query Text", description="Text to search for (for indexes with a managed embedding model)")
    query_vector_json: str = Field(
        "", title="Query Vector (JSON)", description="JSON array of floats representing the query embedding vector (for self-managed embeddings)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    num_results: Optional[int] = Field(None, title="Number of Results", description="Number of results to return")
    filters_json: str = Field(
        "", title="Filters (JSON)", description="JSON object of filters to apply to the query",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _query_vector_search_index(c, host, token) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "columns": _parse_json_field(c.columns_json, "Columns") or [],
        "query_text": c.query_text,
        "query_vector": _parse_json_field(c.query_vector_json, "Query Vector"),
        "num_results": c.num_results,
        "filters_json": c.filters_json or None,
    }
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/query", json_body=body, action_name="query_vector_search_index")


class DatabricksQueryVectorSearchIndexNextPageConfig(BaseModel):
    """Retrieve the next page of vector search query results"""
    operation: Literal["query_vector_search_index_next_page"] = Field(
        "query_vector_search_index_next_page",
        json_schema_extra={"const": "query_vector_search_index_next_page", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Query Vector Search Index Next Page"},
        title="Query Vector Search Index Next Page",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index being queried")
    page_token: str = Field(..., title="Page Token", description="Page token returned from a previous query call")
    endpoint_name: Optional[str] = Field(None, title="Endpoint Name", description="Name of the endpoint hosting the index")


async def _query_vector_search_index_next_page(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/query-next-page", json_body={"page_token": c.page_token, "endpoint_name": c.endpoint_name}, action_name="query_vector_search_index_next_page")


class DatabricksScanVectorSearchIndexConfig(BaseModel):
    """Scan the rows of a vector search index"""
    operation: Literal["scan_vector_search_index"] = Field(
        "scan_vector_search_index",
        json_schema_extra={"const": "scan_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Scan Vector Search Index"},
        title="Scan Vector Search Index",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to scan")
    num_results: Optional[int] = Field(None, title="Number of Results", description="Number of rows to return in the scan")
    last_primary_key: Optional[str] = Field(None, title="Last Primary Key", description="Primary key of the last returned row, used to continue the scan")


async def _scan_vector_search_index(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/scan", json_body={"num_results": c.num_results, "last_primary_key": c.last_primary_key}, action_name="scan_vector_search_index")


class DatabricksSyncVectorSearchIndexConfig(BaseModel):
    """Trigger a sync of a Delta Sync vector search index"""
    operation: Literal["sync_vector_search_index"] = Field(
        "sync_vector_search_index",
        json_schema_extra={"const": "sync_vector_search_index", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Sync Vector Search Index"},
        title="Sync Vector Search Index",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the Delta Sync index to sync")


async def _sync_vector_search_index(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/sync", action_name="sync_vector_search_index")


class DatabricksUpsertVectorSearchIndexDataConfig(BaseModel):
    """Upsert rows of data into a Direct Access vector search index"""
    operation: Literal["upsert_vector_search_index_data"] = Field(
        "upsert_vector_search_index_data",
        json_schema_extra={"const": "upsert_vector_search_index_data", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Upsert Vector Search Index Data"},
        title="Upsert Vector Search Index Data",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to upsert data into")
    inputs_json: str = Field(
        "[]", title="Inputs (JSON)", description="JSON array of row objects to upsert into the index",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _upsert_vector_search_index_data(c, host, token) -> Dict[str, Any]:
    rows = _parse_json_field(c.inputs_json, "Inputs") or []
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/upsert-data", json_body={"inputs_json": json.dumps(rows)}, action_name="upsert_vector_search_index_data")


class DatabricksDeleteVectorSearchIndexDataConfig(BaseModel):
    """Delete rows of data from a Direct Access vector search index by primary key"""
    operation: Literal["delete_vector_search_index_data"] = Field(
        "delete_vector_search_index_data",
        json_schema_extra={"const": "delete_vector_search_index_data", "ui:hidden": True,
                           "x-category": "Vector Search", "x-is-trigger": False,
                           "x-display-name": "Delete Vector Search Index Data"},
        title="Delete Vector Search Index Data",
    )
    index_name: str = Field(..., title="Index Name", description="Three-part name of the index to delete data from")
    primary_keys_json: str = Field(
        "[]", title="Primary Keys (JSON)", description="JSON array of primary key values identifying the rows to delete",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _delete_vector_search_index_data(c, host, token) -> Dict[str, Any]:
    keys = _parse_json_field(c.primary_keys_json, "Primary Keys") or []
    return await _databricks_request(host, token, "POST", f"/api/2.0/vector-search/indexes/{c.index_name}/delete-data", json_body={"primary_keys": keys}, action_name="delete_vector_search_index_data")


OPERATION_CONFIGS.extend([
    DatabricksListVectorSearchEndpointsConfig,
    DatabricksCreateVectorSearchEndpointConfig,
    DatabricksGetVectorSearchEndpointConfig,
    DatabricksDeleteVectorSearchEndpointConfig,
    DatabricksListVectorSearchIndexesConfig,
    DatabricksCreateVectorSearchIndexConfig,
    DatabricksGetVectorSearchIndexConfig,
    DatabricksDeleteVectorSearchIndexConfig,
    DatabricksQueryVectorSearchIndexConfig,
    DatabricksQueryVectorSearchIndexNextPageConfig,
    DatabricksScanVectorSearchIndexConfig,
    DatabricksSyncVectorSearchIndexConfig,
    DatabricksUpsertVectorSearchIndexDataConfig,
    DatabricksDeleteVectorSearchIndexDataConfig,
])
OPERATION_HANDLERS.update({
    "list_vector_search_endpoints": _list_vector_search_endpoints,
    "create_vector_search_endpoint": _create_vector_search_endpoint,
    "get_vector_search_endpoint": _get_vector_search_endpoint,
    "delete_vector_search_endpoint": _delete_vector_search_endpoint,
    "list_vector_search_indexes": _list_vector_search_indexes,
    "create_vector_search_index": _create_vector_search_index,
    "get_vector_search_index": _get_vector_search_index,
    "delete_vector_search_index": _delete_vector_search_index,
    "query_vector_search_index": _query_vector_search_index,
    "query_vector_search_index_next_page": _query_vector_search_index_next_page,
    "scan_vector_search_index": _scan_vector_search_index,
    "sync_vector_search_index": _sync_vector_search_index,
    "upsert_vector_search_index_data": _upsert_vector_search_index_data,
    "delete_vector_search_index_data": _delete_vector_search_index_data,
})


# ---- MLflow Experiments (21 ops) ----
class DatabricksMlflowCreateExperimentConfig(BaseModel):
    """Create a new MLflow experiment."""
    operation: Literal["mlflow_create_experiment"] = Field(
        "mlflow_create_experiment",
        json_schema_extra={"const": "mlflow_create_experiment", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Create Experiment"},
        title="Create Experiment",
    )
    name: str = Field(..., title="Name", description="Unique experiment name.")
    artifact_location: Optional[str] = Field(None, title="Artifact Location", description="Location to store run artifacts.")
    tags_json: str = Field("[]", title="Tags (JSON)", description="Experiment tags as a JSON list of {key, value} objects.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_create_experiment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/create",
        json_body={"name": c.name, "artifact_location": c.artifact_location,
                   "tags": _parse_json_field(c.tags_json, "Tags")},
        action_name="mlflow_create_experiment")


class DatabricksMlflowGetExperimentConfig(BaseModel):
    """Get metadata for an MLflow experiment by ID."""
    operation: Literal["mlflow_get_experiment"] = Field(
        "mlflow_get_experiment",
        json_schema_extra={"const": "mlflow_get_experiment", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Experiment"},
        title="Get Experiment",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to fetch.")


async def _mlflow_get_experiment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/experiments/get",
        params={"experiment_id": c.experiment_id},
        action_name="mlflow_get_experiment")


class DatabricksMlflowGetExperimentByNameConfig(BaseModel):
    """Get metadata for an MLflow experiment by name."""
    operation: Literal["mlflow_get_experiment_by_name"] = Field(
        "mlflow_get_experiment_by_name",
        json_schema_extra={"const": "mlflow_get_experiment_by_name", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Experiment By Name"},
        title="Get Experiment By Name",
    )
    experiment_name: str = Field(..., title="Experiment Name", description="Name of the experiment to fetch.")


async def _mlflow_get_experiment_by_name(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/experiments/get-by-name",
        params={"experiment_name": c.experiment_name},
        action_name="mlflow_get_experiment_by_name")


class DatabricksMlflowSearchExperimentsConfig(BaseModel):
    """Search for MLflow experiments matching filter criteria."""
    operation: Literal["mlflow_search_experiments"] = Field(
        "mlflow_search_experiments",
        json_schema_extra={"const": "mlflow_search_experiments", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Search Experiments"},
        title="Search Experiments",
    )
    filter: Optional[str] = Field(None, title="Filter", description="Filter query string, e.g. \"name LIKE 'demo%'\".")
    max_results: Optional[int] = Field(None, title="Max Results", description="Maximum number of experiments to return.")
    order_by_json: str = Field("[]", title="Order By (JSON)", description="JSON list of order-by clauses, e.g. [\"name ASC\"].",
                               json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for the next page of results.")
    view_type: Optional[str] = Field(None, title="View Type", description="Which experiments to include.",
                                     json_schema_extra={"enum": ["ACTIVE_ONLY", "DELETED_ONLY", "ALL"],
                                                        "enumNames": ["Active Only", "Deleted Only", "All"],
                                                        "x-enum-searchable": True})


async def _mlflow_search_experiments(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/search",
        json_body={"filter": c.filter, "max_results": c.max_results,
                   "order_by": _parse_json_field(c.order_by_json, "Order By"),
                   "page_token": c.page_token, "view_type": c.view_type},
        action_name="mlflow_search_experiments")


class DatabricksMlflowDeleteExperimentConfig(BaseModel):
    """Mark an MLflow experiment as deleted."""
    operation: Literal["mlflow_delete_experiment"] = Field(
        "mlflow_delete_experiment",
        json_schema_extra={"const": "mlflow_delete_experiment", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Delete Experiment"},
        title="Delete Experiment",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to delete.")


async def _mlflow_delete_experiment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/delete",
        json_body={"experiment_id": c.experiment_id},
        action_name="mlflow_delete_experiment")


class DatabricksMlflowRestoreExperimentConfig(BaseModel):
    """Restore a deleted MLflow experiment."""
    operation: Literal["mlflow_restore_experiment"] = Field(
        "mlflow_restore_experiment",
        json_schema_extra={"const": "mlflow_restore_experiment", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Restore Experiment"},
        title="Restore Experiment",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to restore.")


async def _mlflow_restore_experiment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/restore",
        json_body={"experiment_id": c.experiment_id},
        action_name="mlflow_restore_experiment")


class DatabricksMlflowUpdateExperimentConfig(BaseModel):
    """Update an MLflow experiment's name."""
    operation: Literal["mlflow_update_experiment"] = Field(
        "mlflow_update_experiment",
        json_schema_extra={"const": "mlflow_update_experiment", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Update Experiment"},
        title="Update Experiment",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to update.")
    new_name: Optional[str] = Field(None, title="New Name", description="New name for the experiment.")


async def _mlflow_update_experiment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/update",
        json_body={"experiment_id": c.experiment_id, "new_name": c.new_name},
        action_name="mlflow_update_experiment")


class DatabricksMlflowSetExperimentTagConfig(BaseModel):
    """Set a tag on an MLflow experiment."""
    operation: Literal["mlflow_set_experiment_tag"] = Field(
        "mlflow_set_experiment_tag",
        json_schema_extra={"const": "mlflow_set_experiment_tag", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Set Experiment Tag"},
        title="Set Experiment Tag",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to tag.")
    key: str = Field(..., title="Key", description="Tag key.")
    value: str = Field(..., title="Value", description="Tag value.")


async def _mlflow_set_experiment_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/experiments/set-experiment-tag",
        json_body={"experiment_id": c.experiment_id, "key": c.key, "value": c.value},
        action_name="mlflow_set_experiment_tag")


class DatabricksMlflowCreateRunConfig(BaseModel):
    """Create a new MLflow run within an experiment."""
    operation: Literal["mlflow_create_run"] = Field(
        "mlflow_create_run",
        json_schema_extra={"const": "mlflow_create_run", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Create Run"},
        title="Create Run",
    )
    experiment_id: str = Field(..., title="Experiment ID", description="ID of the experiment to create the run in.")
    start_time: Optional[int] = Field(None, title="Start Time", description="Unix timestamp in milliseconds of when the run started.")
    run_name: Optional[str] = Field(None, title="Run Name", description="Name for the run.")
    tags_json: str = Field("[]", title="Tags (JSON)", description="Run tags as a JSON list of {key, value} objects.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_create_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/create",
        json_body={"experiment_id": c.experiment_id, "start_time": c.start_time,
                   "run_name": c.run_name, "tags": _parse_json_field(c.tags_json, "Tags")},
        action_name="mlflow_create_run")


class DatabricksMlflowGetRunConfig(BaseModel):
    """Get metadata, metrics, params and tags for an MLflow run."""
    operation: Literal["mlflow_get_run"] = Field(
        "mlflow_get_run",
        json_schema_extra={"const": "mlflow_get_run", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Run"},
        title="Get Run",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to fetch.")


async def _mlflow_get_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/runs/get",
        params={"run_id": c.run_id},
        action_name="mlflow_get_run")


class DatabricksMlflowUpdateRunConfig(BaseModel):
    """Update the status, end time or name of an MLflow run."""
    operation: Literal["mlflow_update_run"] = Field(
        "mlflow_update_run",
        json_schema_extra={"const": "mlflow_update_run", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Update Run"},
        title="Update Run",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to update.")
    status: Optional[str] = Field(None, title="Status", description="New run status.",
                                  json_schema_extra={"enum": ["RUNNING", "SCHEDULED", "FINISHED", "FAILED", "KILLED"],
                                                     "enumNames": ["Running", "Scheduled", "Finished", "Failed", "Killed"],
                                                     "x-enum-searchable": True})
    end_time: Optional[int] = Field(None, title="End Time", description="Unix timestamp in milliseconds of when the run ended.")
    run_name: Optional[str] = Field(None, title="Run Name", description="New name for the run.")


async def _mlflow_update_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/update",
        json_body={"run_id": c.run_id, "status": c.status, "end_time": c.end_time, "run_name": c.run_name},
        action_name="mlflow_update_run")


class DatabricksMlflowDeleteRunConfig(BaseModel):
    """Mark an MLflow run as deleted."""
    operation: Literal["mlflow_delete_run"] = Field(
        "mlflow_delete_run",
        json_schema_extra={"const": "mlflow_delete_run", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Delete Run"},
        title="Delete Run",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to delete.")


async def _mlflow_delete_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/delete",
        json_body={"run_id": c.run_id},
        action_name="mlflow_delete_run")


class DatabricksMlflowRestoreRunConfig(BaseModel):
    """Restore a deleted MLflow run."""
    operation: Literal["mlflow_restore_run"] = Field(
        "mlflow_restore_run",
        json_schema_extra={"const": "mlflow_restore_run", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Restore Run"},
        title="Restore Run",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to restore.")


async def _mlflow_restore_run(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/restore",
        json_body={"run_id": c.run_id},
        action_name="mlflow_restore_run")


class DatabricksMlflowSearchRunsConfig(BaseModel):
    """Search for MLflow runs across one or more experiments."""
    operation: Literal["mlflow_search_runs"] = Field(
        "mlflow_search_runs",
        json_schema_extra={"const": "mlflow_search_runs", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Search Runs"},
        title="Search Runs",
    )
    experiment_ids_json: str = Field("[]", title="Experiment IDs (JSON)", description="JSON list of experiment IDs to search over.",
                                     json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    filter: Optional[str] = Field(None, title="Filter", description="Filter query string, e.g. \"metrics.rmse < 1\".")
    max_results: Optional[int] = Field(None, title="Max Results", description="Maximum number of runs to return.")
    order_by_json: str = Field("[]", title="Order By (JSON)", description="JSON list of order-by clauses, e.g. [\"metrics.rmse ASC\"].",
                               json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for the next page of results.")
    run_view_type: Optional[str] = Field(None, title="Run View Type", description="Which runs to include.",
                                         json_schema_extra={"enum": ["ACTIVE_ONLY", "DELETED_ONLY", "ALL"],
                                                            "enumNames": ["Active Only", "Deleted Only", "All"],
                                                            "x-enum-searchable": True})


async def _mlflow_search_runs(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/search",
        json_body={"experiment_ids": _parse_json_field(c.experiment_ids_json, "Experiment IDs"),
                   "filter": c.filter, "max_results": c.max_results,
                   "order_by": _parse_json_field(c.order_by_json, "Order By"),
                   "page_token": c.page_token, "run_view_type": c.run_view_type},
        action_name="mlflow_search_runs")


class DatabricksMlflowLogMetricConfig(BaseModel):
    """Log a metric value for an MLflow run."""
    operation: Literal["mlflow_log_metric"] = Field(
        "mlflow_log_metric",
        json_schema_extra={"const": "mlflow_log_metric", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Log Metric"},
        title="Log Metric",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to log the metric to.")
    key: str = Field(..., title="Key", description="Name of the metric.")
    value: float = Field(..., title="Value", description="Numeric metric value.")
    timestamp: Optional[int] = Field(None, title="Timestamp", description="Unix timestamp in milliseconds when the metric was recorded.")
    step: Optional[int] = Field(None, title="Step", description="Step at which the metric was recorded.")


async def _mlflow_log_metric(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/log-metric",
        json_body={"run_id": c.run_id, "key": c.key, "value": c.value,
                   "timestamp": c.timestamp, "step": c.step},
        action_name="mlflow_log_metric")


class DatabricksMlflowLogParamConfig(BaseModel):
    """Log a parameter (hyperparameter) for an MLflow run."""
    operation: Literal["mlflow_log_param"] = Field(
        "mlflow_log_param",
        json_schema_extra={"const": "mlflow_log_param", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Log Param"},
        title="Log Param",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to log the parameter to.")
    key: str = Field(..., title="Key", description="Name of the parameter.")
    value: str = Field(..., title="Value", description="Parameter value (string).")


async def _mlflow_log_param(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/log-parameter",
        json_body={"run_id": c.run_id, "key": c.key, "value": c.value},
        action_name="mlflow_log_param")


class DatabricksMlflowLogBatchConfig(BaseModel):
    """Log a batch of metrics, params and tags to an MLflow run in one call."""
    operation: Literal["mlflow_log_batch"] = Field(
        "mlflow_log_batch",
        json_schema_extra={"const": "mlflow_log_batch", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Log Batch"},
        title="Log Batch",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to log to.")
    metrics_json: str = Field("[]", title="Metrics (JSON)", description="JSON list of metric objects {key, value, timestamp, step}.",
                              json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    params_json: str = Field("[]", title="Params (JSON)", description="JSON list of param objects {key, value}.",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    tags_json: str = Field("[]", title="Tags (JSON)", description="JSON list of tag objects {key, value}.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_log_batch(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/log-batch",
        json_body={"run_id": c.run_id,
                   "metrics": _parse_json_field(c.metrics_json, "Metrics"),
                   "params": _parse_json_field(c.params_json, "Params"),
                   "tags": _parse_json_field(c.tags_json, "Tags")},
        action_name="mlflow_log_batch")


class DatabricksMlflowSetRunTagConfig(BaseModel):
    """Set a tag on an MLflow run."""
    operation: Literal["mlflow_set_run_tag"] = Field(
        "mlflow_set_run_tag",
        json_schema_extra={"const": "mlflow_set_run_tag", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Set Run Tag"},
        title="Set Run Tag",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to tag.")
    key: str = Field(..., title="Key", description="Tag key.")
    value: str = Field(..., title="Value", description="Tag value.")


async def _mlflow_set_run_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/set-tag",
        json_body={"run_id": c.run_id, "key": c.key, "value": c.value},
        action_name="mlflow_set_run_tag")


class DatabricksMlflowDeleteRunTagConfig(BaseModel):
    """Delete a tag from an MLflow run."""
    operation: Literal["mlflow_delete_run_tag"] = Field(
        "mlflow_delete_run_tag",
        json_schema_extra={"const": "mlflow_delete_run_tag", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Delete Run Tag"},
        title="Delete Run Tag",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run to remove the tag from.")
    key: str = Field(..., title="Key", description="Tag key to delete.")


async def _mlflow_delete_run_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/runs/delete-tag",
        json_body={"run_id": c.run_id, "key": c.key},
        action_name="mlflow_delete_run_tag")


class DatabricksMlflowGetMetricHistoryConfig(BaseModel):
    """Get the full logged history of a metric for an MLflow run."""
    operation: Literal["mlflow_get_metric_history"] = Field(
        "mlflow_get_metric_history",
        json_schema_extra={"const": "mlflow_get_metric_history", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Metric History"},
        title="Get Metric History",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run.")
    metric_key: str = Field(..., title="Metric Key", description="Name of the metric to fetch history for.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for the next page of results.")
    max_results: Optional[int] = Field(None, title="Max Results", description="Maximum number of metric records to return.")


async def _mlflow_get_metric_history(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/metrics/get-history",
        params={"run_id": c.run_id, "metric_key": c.metric_key,
                "page_token": c.page_token, "max_results": c.max_results},
        action_name="mlflow_get_metric_history")


class DatabricksMlflowListArtifactsConfig(BaseModel):
    """List artifacts stored for an MLflow run."""
    operation: Literal["mlflow_list_artifacts"] = Field(
        "mlflow_list_artifacts",
        json_schema_extra={"const": "mlflow_list_artifacts", "ui:hidden": True,
                           "x-category": "MLflow Experiments", "x-is-trigger": False,
                           "x-display-name": "List Artifacts"},
        title="List Artifacts",
    )
    run_id: str = Field(..., title="Run ID", description="ID of the run whose artifacts to list.")
    path: Optional[str] = Field(None, title="Path", description="Relative artifact path to list under.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Token for the next page of results.")


async def _mlflow_list_artifacts(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/artifacts/list",
        params={"run_id": c.run_id, "path": c.path, "page_token": c.page_token},
        action_name="mlflow_list_artifacts")


OPERATION_CONFIGS.extend([
    DatabricksMlflowCreateExperimentConfig,
    DatabricksMlflowGetExperimentConfig,
    DatabricksMlflowGetExperimentByNameConfig,
    DatabricksMlflowSearchExperimentsConfig,
    DatabricksMlflowDeleteExperimentConfig,
    DatabricksMlflowRestoreExperimentConfig,
    DatabricksMlflowUpdateExperimentConfig,
    DatabricksMlflowSetExperimentTagConfig,
    DatabricksMlflowCreateRunConfig,
    DatabricksMlflowGetRunConfig,
    DatabricksMlflowUpdateRunConfig,
    DatabricksMlflowDeleteRunConfig,
    DatabricksMlflowRestoreRunConfig,
    DatabricksMlflowSearchRunsConfig,
    DatabricksMlflowLogMetricConfig,
    DatabricksMlflowLogParamConfig,
    DatabricksMlflowLogBatchConfig,
    DatabricksMlflowSetRunTagConfig,
    DatabricksMlflowDeleteRunTagConfig,
    DatabricksMlflowGetMetricHistoryConfig,
    DatabricksMlflowListArtifactsConfig,
])
OPERATION_HANDLERS.update({
    "mlflow_create_experiment": _mlflow_create_experiment,
    "mlflow_get_experiment": _mlflow_get_experiment,
    "mlflow_get_experiment_by_name": _mlflow_get_experiment_by_name,
    "mlflow_search_experiments": _mlflow_search_experiments,
    "mlflow_delete_experiment": _mlflow_delete_experiment,
    "mlflow_restore_experiment": _mlflow_restore_experiment,
    "mlflow_update_experiment": _mlflow_update_experiment,
    "mlflow_set_experiment_tag": _mlflow_set_experiment_tag,
    "mlflow_create_run": _mlflow_create_run,
    "mlflow_get_run": _mlflow_get_run,
    "mlflow_update_run": _mlflow_update_run,
    "mlflow_delete_run": _mlflow_delete_run,
    "mlflow_restore_run": _mlflow_restore_run,
    "mlflow_search_runs": _mlflow_search_runs,
    "mlflow_log_metric": _mlflow_log_metric,
    "mlflow_log_param": _mlflow_log_param,
    "mlflow_log_batch": _mlflow_log_batch,
    "mlflow_set_run_tag": _mlflow_set_run_tag,
    "mlflow_delete_run_tag": _mlflow_delete_run_tag,
    "mlflow_get_metric_history": _mlflow_get_metric_history,
    "mlflow_list_artifacts": _mlflow_list_artifacts,
})


# ---- MLflow Model Registry (24 ops) ----
class DatabricksMlflowCreateRegisteredModelConfig(BaseModel):
    """Create a new registered model in the MLflow Model Registry."""
    operation: Literal["mlflow_create_registered_model"] = Field(
        "mlflow_create_registered_model",
        json_schema_extra={"const": "mlflow_create_registered_model", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Create Registered Model"},
        title="Create Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Unique name of the registered model.")
    description: Optional[str] = Field(None, title="Description", description="Optional description for the registered model.")
    tags_json: str = Field("[]", title="Tags (JSON)", description="Array of tag objects, each {\"key\":...,\"value\":...}.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_create_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registered-models/create",
                                     json_body={"name": c.name, "description": c.description,
                                                "tags": _parse_json_field(c.tags_json, "Tags")},
                                     action_name="mlflow_create_registered_model")


class DatabricksMlflowGetRegisteredModelConfig(BaseModel):
    """Get the details of a registered model."""
    operation: Literal["mlflow_get_registered_model"] = Field(
        "mlflow_get_registered_model",
        json_schema_extra={"const": "mlflow_get_registered_model", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Get Registered Model"},
        title="Get Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model to fetch.")


async def _mlflow_get_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/registered-models/get",
                                     params={"name": c.name},
                                     action_name="mlflow_get_registered_model")


class DatabricksMlflowRenameRegisteredModelConfig(BaseModel):
    """Rename a registered model."""
    operation: Literal["mlflow_rename_registered_model"] = Field(
        "mlflow_rename_registered_model",
        json_schema_extra={"const": "mlflow_rename_registered_model", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Rename Registered Model"},
        title="Rename Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Current name of the registered model.")
    new_name: str = Field(..., title="New Name", description="New name for the registered model.")


async def _mlflow_rename_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registered-models/rename",
                                     json_body={"name": c.name, "new_name": c.new_name},
                                     action_name="mlflow_rename_registered_model")


class DatabricksMlflowUpdateRegisteredModelConfig(BaseModel):
    """Update the description of a registered model."""
    operation: Literal["mlflow_update_registered_model"] = Field(
        "mlflow_update_registered_model",
        json_schema_extra={"const": "mlflow_update_registered_model", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Update Registered Model"},
        title="Update Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    description: Optional[str] = Field(None, title="Description", description="New description for the registered model.")


async def _mlflow_update_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "PATCH", "/api/2.0/mlflow/registered-models/update",
                                     json_body={"name": c.name, "description": c.description},
                                     action_name="mlflow_update_registered_model")


class DatabricksMlflowDeleteRegisteredModelConfig(BaseModel):
    """Delete a registered model."""
    operation: Literal["mlflow_delete_registered_model"] = Field(
        "mlflow_delete_registered_model",
        json_schema_extra={"const": "mlflow_delete_registered_model", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Delete Registered Model"},
        title="Delete Registered Model",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model to delete.")


async def _mlflow_delete_registered_model(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", "/api/2.0/mlflow/registered-models/delete",
                                     json_body={"name": c.name},
                                     action_name="mlflow_delete_registered_model")


class DatabricksMlflowSearchRegisteredModelsConfig(BaseModel):
    """Search for registered models matching a filter."""
    operation: Literal["mlflow_search_registered_models"] = Field(
        "mlflow_search_registered_models",
        json_schema_extra={"const": "mlflow_search_registered_models", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Search Registered Models"},
        title="Search Registered Models",
    )
    filter: Optional[str] = Field(None, title="Filter", description="Filter query string, e.g. name LIKE 'prod%'.")
    max_results: Optional[str] = Field(None, title="Max Results", description="Maximum number of models to return.")
    order_by_json: str = Field("[]", title="Order By (JSON)", description="Array of order-by clauses, e.g. [\"name ASC\"].",
                               json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token from a previous response.")


async def _mlflow_search_registered_models(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/registered-models/search",
                                     params={"filter": c.filter, "max_results": c.max_results,
                                             "order_by": _parse_json_field(c.order_by_json, "Order By"),
                                             "page_token": c.page_token},
                                     action_name="mlflow_search_registered_models")


class DatabricksMlflowGetLatestModelVersionsConfig(BaseModel):
    """Get the latest model versions for a registered model, optionally filtered by stages."""
    operation: Literal["mlflow_get_latest_model_versions"] = Field(
        "mlflow_get_latest_model_versions",
        json_schema_extra={"const": "mlflow_get_latest_model_versions", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Get Latest Model Versions"},
        title="Get Latest Model Versions",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    stages_json: str = Field("[]", title="Stages (JSON)", description="Array of stages to filter by, e.g. [\"Production\",\"Staging\"].",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_get_latest_model_versions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registered-models/get-latest-versions",
                                     json_body={"name": c.name, "stages": _parse_json_field(c.stages_json, "Stages")},
                                     action_name="mlflow_get_latest_model_versions")


class DatabricksMlflowSetRegisteredModelTagConfig(BaseModel):
    """Set a tag on a registered model."""
    operation: Literal["mlflow_set_registered_model_tag"] = Field(
        "mlflow_set_registered_model_tag",
        json_schema_extra={"const": "mlflow_set_registered_model_tag", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Set Registered Model Tag"},
        title="Set Registered Model Tag",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    key: str = Field(..., title="Tag Key", description="Tag key to set.")
    value: str = Field(..., title="Tag Value", description="Tag value to set.")


async def _mlflow_set_registered_model_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registered-models/set-tag",
                                     json_body={"name": c.name, "key": c.key, "value": c.value},
                                     action_name="mlflow_set_registered_model_tag")


class DatabricksMlflowDeleteRegisteredModelTagConfig(BaseModel):
    """Delete a tag from a registered model."""
    operation: Literal["mlflow_delete_registered_model_tag"] = Field(
        "mlflow_delete_registered_model_tag",
        json_schema_extra={"const": "mlflow_delete_registered_model_tag", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Delete Registered Model Tag"},
        title="Delete Registered Model Tag",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    key: str = Field(..., title="Tag Key", description="Tag key to delete.")


async def _mlflow_delete_registered_model_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", "/api/2.0/mlflow/registered-models/delete-tag",
                                     params={"name": c.name, "key": c.key},
                                     action_name="mlflow_delete_registered_model_tag")


class DatabricksMlflowSetRegisteredModelAliasConfig(BaseModel):
    """Set an alias pointing to a specific version of a registered model."""
    operation: Literal["mlflow_set_registered_model_alias"] = Field(
        "mlflow_set_registered_model_alias",
        json_schema_extra={"const": "mlflow_set_registered_model_alias", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Set Registered Model Alias"},
        title="Set Registered Model Alias",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    alias: str = Field(..., title="Alias", description="Alias name to assign.")
    version: str = Field(..., title="Version", description="Model version the alias should point to.")


async def _mlflow_set_registered_model_alias(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registered-models/alias",
                                     json_body={"name": c.name, "alias": c.alias, "version": c.version},
                                     action_name="mlflow_set_registered_model_alias")


class DatabricksMlflowCreateModelVersionConfig(BaseModel):
    """Create a new version of a registered model."""
    operation: Literal["mlflow_create_model_version"] = Field(
        "mlflow_create_model_version",
        json_schema_extra={"const": "mlflow_create_model_version", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Create Model Version"},
        title="Create Model Version",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    source: str = Field(..., title="Source", description="URI/path indicating the model artifact source location.")
    run_id: Optional[str] = Field(None, title="Run ID", description="MLflow run ID that generated this model version.")
    description: Optional[str] = Field(None, title="Description", description="Optional description for the model version.")
    tags_json: str = Field("[]", title="Tags (JSON)", description="Array of tag objects, each {\"key\":...,\"value\":...}.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_create_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/model-versions/create",
                                     json_body={"name": c.name, "source": c.source, "run_id": c.run_id,
                                                "description": c.description,
                                                "tags": _parse_json_field(c.tags_json, "Tags")},
                                     action_name="mlflow_create_model_version")


class DatabricksMlflowGetModelVersionConfig(BaseModel):
    """Get the details of a specific model version."""
    operation: Literal["mlflow_get_model_version"] = Field(
        "mlflow_get_model_version",
        json_schema_extra={"const": "mlflow_get_model_version", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Get Model Version"},
        title="Get Model Version",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version to fetch.")


async def _mlflow_get_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/model-versions/get",
                                     params={"name": c.name, "version": c.version},
                                     action_name="mlflow_get_model_version")


class DatabricksMlflowUpdateModelVersionConfig(BaseModel):
    """Update the description of a model version."""
    operation: Literal["mlflow_update_model_version"] = Field(
        "mlflow_update_model_version",
        json_schema_extra={"const": "mlflow_update_model_version", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Update Model Version"},
        title="Update Model Version",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version to update.")
    description: Optional[str] = Field(None, title="Description", description="New description for the model version.")


async def _mlflow_update_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "PATCH", "/api/2.0/mlflow/model-versions/update",
                                     json_body={"name": c.name, "version": c.version, "description": c.description},
                                     action_name="mlflow_update_model_version")


class DatabricksMlflowDeleteModelVersionConfig(BaseModel):
    """Delete a specific model version."""
    operation: Literal["mlflow_delete_model_version"] = Field(
        "mlflow_delete_model_version",
        json_schema_extra={"const": "mlflow_delete_model_version", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Delete Model Version"},
        title="Delete Model Version",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version to delete.")


async def _mlflow_delete_model_version(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", "/api/2.0/mlflow/model-versions/delete",
                                     params={"name": c.name, "version": c.version},
                                     action_name="mlflow_delete_model_version")


class DatabricksMlflowSearchModelVersionsConfig(BaseModel):
    """Search for model versions matching a filter."""
    operation: Literal["mlflow_search_model_versions"] = Field(
        "mlflow_search_model_versions",
        json_schema_extra={"const": "mlflow_search_model_versions", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Search Model Versions"},
        title="Search Model Versions",
    )
    filter: Optional[str] = Field(None, title="Filter", description="Filter query string, e.g. name='my_model'.")
    max_results: Optional[str] = Field(None, title="Max Results", description="Maximum number of versions to return.")
    order_by_json: str = Field("[]", title="Order By (JSON)", description="Array of order-by clauses, e.g. [\"version_number DESC\"].",
                               json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token from a previous response.")


async def _mlflow_search_model_versions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/model-versions/search",
                                     params={"filter": c.filter, "max_results": c.max_results,
                                             "order_by": _parse_json_field(c.order_by_json, "Order By"),
                                             "page_token": c.page_token},
                                     action_name="mlflow_search_model_versions")


class DatabricksMlflowGetModelVersionDownloadUriConfig(BaseModel):
    """Get the download URI for a model version's artifacts."""
    operation: Literal["mlflow_get_model_version_download_uri"] = Field(
        "mlflow_get_model_version_download_uri",
        json_schema_extra={"const": "mlflow_get_model_version_download_uri", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Get Model Version Download URI"},
        title="Get Model Version Download URI",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version whose download URI to fetch.")


async def _mlflow_get_model_version_download_uri(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/model-versions/get-download-uri",
                                     params={"name": c.name, "version": c.version},
                                     action_name="mlflow_get_model_version_download_uri")


class DatabricksMlflowTransitionModelVersionStageConfig(BaseModel):
    """Transition a model version to a new stage."""
    operation: Literal["mlflow_transition_model_version_stage"] = Field(
        "mlflow_transition_model_version_stage",
        json_schema_extra={"const": "mlflow_transition_model_version_stage", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Transition Model Version Stage"},
        title="Transition Model Version Stage",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version to transition.")
    stage: str = Field(..., title="Stage", description="Target stage for the model version.",
                       json_schema_extra={"enum": ["None", "Staging", "Production", "Archived"],
                                          "enumNames": ["None", "Staging", "Production", "Archived"],
                                          "x-enum-searchable": True})
    archive_existing_versions: str = Field("false", title="Archive Existing Versions",
                                           description="Archive all existing versions currently in the target stage.",
                                           json_schema_extra={"enum": ["true", "false"],
                                                              "enumNames": ["Yes", "No"],
                                                              "x-enum-searchable": True})


async def _mlflow_transition_model_version_stage(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/model-versions/transition-stage",
                                     json_body={"name": c.name, "version": c.version, "stage": c.stage,
                                                "archive_existing_versions": c.archive_existing_versions == "true"},
                                     action_name="mlflow_transition_model_version_stage")


class DatabricksMlflowSetModelVersionTagConfig(BaseModel):
    """Set a tag on a model version."""
    operation: Literal["mlflow_set_model_version_tag"] = Field(
        "mlflow_set_model_version_tag",
        json_schema_extra={"const": "mlflow_set_model_version_tag", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Set Model Version Tag"},
        title="Set Model Version Tag",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version to tag.")
    key: str = Field(..., title="Tag Key", description="Tag key to set.")
    value: str = Field(..., title="Tag Value", description="Tag value to set.")


async def _mlflow_set_model_version_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/model-versions/set-tag",
                                     json_body={"name": c.name, "version": c.version, "key": c.key, "value": c.value},
                                     action_name="mlflow_set_model_version_tag")


class DatabricksMlflowDeleteModelVersionTagConfig(BaseModel):
    """Delete a tag from a model version."""
    operation: Literal["mlflow_delete_model_version_tag"] = Field(
        "mlflow_delete_model_version_tag",
        json_schema_extra={"const": "mlflow_delete_model_version_tag", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Delete Model Version Tag"},
        title="Delete Model Version Tag",
    )
    name: str = Field(..., title="Model Name", description="Name of the registered model.")
    version: str = Field(..., title="Version", description="Model version whose tag to delete.")
    key: str = Field(..., title="Tag Key", description="Tag key to delete.")


async def _mlflow_delete_model_version_tag(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", "/api/2.0/mlflow/model-versions/delete-tag",
                                     params={"name": c.name, "version": c.version, "key": c.key},
                                     action_name="mlflow_delete_model_version_tag")


class DatabricksMlflowCreateRegistryWebhookConfig(BaseModel):
    """Create a Model Registry webhook that fires on registry events."""
    operation: Literal["mlflow_create_registry_webhook"] = Field(
        "mlflow_create_registry_webhook",
        json_schema_extra={"const": "mlflow_create_registry_webhook", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Create Registry Webhook"},
        title="Create Registry Webhook",
    )
    events_json: str = Field("[]", title="Events (JSON)", description="Array of event names, e.g. [\"MODEL_VERSION_CREATED\"].",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    description: Optional[str] = Field(None, title="Description", description="Optional description for the webhook.")
    status: Optional[str] = Field(None, title="Status", description="Webhook status.",
                                  json_schema_extra={"enum": ["ACTIVE", "TEST_MODE", "DISABLED"],
                                                     "enumNames": ["Active", "Test Mode", "Disabled"],
                                                     "x-enum-searchable": True})
    model_name: Optional[str] = Field(None, title="Model Name", description="Registered model name to scope the webhook to.")
    http_url_spec_json: str = Field("{}", title="HTTP URL Spec (JSON)", description="HTTP URL webhook spec, e.g. {\"url\":...,\"secret\":...}.",
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    job_spec_json: str = Field("{}", title="Job Spec (JSON)", description="Job webhook spec, e.g. {\"job_id\":...,\"workspace_url\":...,\"access_token\":...}.",
                               json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_create_registry_webhook(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registry-webhooks/create",
                                     json_body={"events": _parse_json_field(c.events_json, "Events"),
                                                "description": c.description, "status": c.status,
                                                "model_name": c.model_name,
                                                "http_url_spec": _parse_json_field(c.http_url_spec_json, "HTTP URL Spec"),
                                                "job_spec": _parse_json_field(c.job_spec_json, "Job Spec")},
                                     action_name="mlflow_create_registry_webhook")


class DatabricksMlflowListRegistryWebhooksConfig(BaseModel):
    """List Model Registry webhooks, optionally filtered by model or events."""
    operation: Literal["mlflow_list_registry_webhooks"] = Field(
        "mlflow_list_registry_webhooks",
        json_schema_extra={"const": "mlflow_list_registry_webhooks", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "List Registry Webhooks"},
        title="List Registry Webhooks",
    )
    model_name: Optional[str] = Field(None, title="Model Name", description="Filter webhooks by registered model name.")
    events_json: str = Field("[]", title="Events (JSON)", description="Array of event names to filter by.",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_list_registry_webhooks(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/mlflow/registry-webhooks/list",
                                     params={"model_name": c.model_name,
                                             "events": _parse_json_field(c.events_json, "Events")},
                                     action_name="mlflow_list_registry_webhooks")


class DatabricksMlflowUpdateRegistryWebhookConfig(BaseModel):
    """Update an existing Model Registry webhook."""
    operation: Literal["mlflow_update_registry_webhook"] = Field(
        "mlflow_update_registry_webhook",
        json_schema_extra={"const": "mlflow_update_registry_webhook", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Update Registry Webhook"},
        title="Update Registry Webhook",
    )
    id: str = Field(..., title="Webhook ID", description="ID of the webhook to update.")
    events_json: str = Field("[]", title="Events (JSON)", description="Array of event names, e.g. [\"MODEL_VERSION_CREATED\"].",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    status: Optional[str] = Field(None, title="Status", description="Webhook status.",
                                  json_schema_extra={"enum": ["ACTIVE", "TEST_MODE", "DISABLED"],
                                                     "enumNames": ["Active", "Test Mode", "Disabled"],
                                                     "x-enum-searchable": True})
    http_url_spec_json: str = Field("{}", title="HTTP URL Spec (JSON)", description="HTTP URL webhook spec, e.g. {\"url\":...,\"secret\":...}.",
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _mlflow_update_registry_webhook(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "PATCH", "/api/2.0/mlflow/registry-webhooks/update",
                                     json_body={"id": c.id,
                                                "events": _parse_json_field(c.events_json, "Events"),
                                                "status": c.status,
                                                "http_url_spec": _parse_json_field(c.http_url_spec_json, "HTTP URL Spec")},
                                     action_name="mlflow_update_registry_webhook")


class DatabricksMlflowDeleteRegistryWebhookConfig(BaseModel):
    """Delete a Model Registry webhook."""
    operation: Literal["mlflow_delete_registry_webhook"] = Field(
        "mlflow_delete_registry_webhook",
        json_schema_extra={"const": "mlflow_delete_registry_webhook", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Delete Registry Webhook"},
        title="Delete Registry Webhook",
    )
    id: str = Field(..., title="Webhook ID", description="ID of the webhook to delete.")


async def _mlflow_delete_registry_webhook(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", "/api/2.0/mlflow/registry-webhooks/delete",
                                     params={"id": c.id},
                                     action_name="mlflow_delete_registry_webhook")


class DatabricksMlflowTestRegistryWebhookConfig(BaseModel):
    """Send a test event to a Model Registry webhook."""
    operation: Literal["mlflow_test_registry_webhook"] = Field(
        "mlflow_test_registry_webhook",
        json_schema_extra={"const": "mlflow_test_registry_webhook", "ui:hidden": True,
                           "x-category": "MLflow Model Registry", "x-is-trigger": False,
                           "x-display-name": "Test Registry Webhook"},
        title="Test Registry Webhook",
    )
    id: str = Field(..., title="Webhook ID", description="ID of the webhook to test.")
    event: Optional[str] = Field(None, title="Event", description="Specific event to simulate for the test.")


async def _mlflow_test_registry_webhook(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/mlflow/registry-webhooks/test",
                                     json_body={"id": c.id, "event": c.event},
                                     action_name="mlflow_test_registry_webhook")


OPERATION_CONFIGS.extend([
    DatabricksMlflowCreateRegisteredModelConfig,
    DatabricksMlflowGetRegisteredModelConfig,
    DatabricksMlflowRenameRegisteredModelConfig,
    DatabricksMlflowUpdateRegisteredModelConfig,
    DatabricksMlflowDeleteRegisteredModelConfig,
    DatabricksMlflowSearchRegisteredModelsConfig,
    DatabricksMlflowGetLatestModelVersionsConfig,
    DatabricksMlflowSetRegisteredModelTagConfig,
    DatabricksMlflowDeleteRegisteredModelTagConfig,
    DatabricksMlflowSetRegisteredModelAliasConfig,
    DatabricksMlflowCreateModelVersionConfig,
    DatabricksMlflowGetModelVersionConfig,
    DatabricksMlflowUpdateModelVersionConfig,
    DatabricksMlflowDeleteModelVersionConfig,
    DatabricksMlflowSearchModelVersionsConfig,
    DatabricksMlflowGetModelVersionDownloadUriConfig,
    DatabricksMlflowTransitionModelVersionStageConfig,
    DatabricksMlflowSetModelVersionTagConfig,
    DatabricksMlflowDeleteModelVersionTagConfig,
    DatabricksMlflowCreateRegistryWebhookConfig,
    DatabricksMlflowListRegistryWebhooksConfig,
    DatabricksMlflowUpdateRegistryWebhookConfig,
    DatabricksMlflowDeleteRegistryWebhookConfig,
    DatabricksMlflowTestRegistryWebhookConfig,
])
OPERATION_HANDLERS.update({
    "mlflow_create_registered_model": _mlflow_create_registered_model,
    "mlflow_get_registered_model": _mlflow_get_registered_model,
    "mlflow_rename_registered_model": _mlflow_rename_registered_model,
    "mlflow_update_registered_model": _mlflow_update_registered_model,
    "mlflow_delete_registered_model": _mlflow_delete_registered_model,
    "mlflow_search_registered_models": _mlflow_search_registered_models,
    "mlflow_get_latest_model_versions": _mlflow_get_latest_model_versions,
    "mlflow_set_registered_model_tag": _mlflow_set_registered_model_tag,
    "mlflow_delete_registered_model_tag": _mlflow_delete_registered_model_tag,
    "mlflow_set_registered_model_alias": _mlflow_set_registered_model_alias,
    "mlflow_create_model_version": _mlflow_create_model_version,
    "mlflow_get_model_version": _mlflow_get_model_version,
    "mlflow_update_model_version": _mlflow_update_model_version,
    "mlflow_delete_model_version": _mlflow_delete_model_version,
    "mlflow_search_model_versions": _mlflow_search_model_versions,
    "mlflow_get_model_version_download_uri": _mlflow_get_model_version_download_uri,
    "mlflow_transition_model_version_stage": _mlflow_transition_model_version_stage,
    "mlflow_set_model_version_tag": _mlflow_set_model_version_tag,
    "mlflow_delete_model_version_tag": _mlflow_delete_model_version_tag,
    "mlflow_create_registry_webhook": _mlflow_create_registry_webhook,
    "mlflow_list_registry_webhooks": _mlflow_list_registry_webhooks,
    "mlflow_update_registry_webhook": _mlflow_update_registry_webhook,
    "mlflow_delete_registry_webhook": _mlflow_delete_registry_webhook,
    "mlflow_test_registry_webhook": _mlflow_test_registry_webhook,
})


# ---- Feature Store (10 ops) ----
class DatabricksListOnlineStoresConfig(BaseModel):
    """List all online stores in the workspace."""
    operation: Literal["list_online_stores"] = Field(
        "list_online_stores",
        json_schema_extra={"const": "list_online_stores", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "List Online Stores"},
        title="List Online Stores",
    )
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token returned by a previous list call.")


class DatabricksCreateOnlineStoreConfig(BaseModel):
    """Create a new online store."""
    operation: Literal["create_online_store"] = Field(
        "create_online_store",
        json_schema_extra={"const": "create_online_store", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Create Online Store"},
        title="Create Online Store",
    )
    online_store_json: str = Field(
        "{}", title="Online Store (JSON)",
        description="Full online store object (name, capacity, read_replica_count, etc).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetOnlineStoreConfig(BaseModel):
    """Get an online store by name."""
    operation: Literal["get_online_store"] = Field(
        "get_online_store",
        json_schema_extra={"const": "get_online_store", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Get Online Store"},
        title="Get Online Store",
    )
    name: str = Field(..., title="Online Store Name", description="Name of the online store to retrieve.")


class DatabricksUpdateOnlineStoreConfig(BaseModel):
    """Update an existing online store."""
    operation: Literal["update_online_store"] = Field(
        "update_online_store",
        json_schema_extra={"const": "update_online_store", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Update Online Store"},
        title="Update Online Store",
    )
    name: str = Field(..., title="Online Store Name", description="Name of the online store to update.")
    update_mask: str = Field(..., title="Update Mask", description="Comma-separated list of fields to update (e.g. 'capacity,read_replica_count').")
    online_store_json: str = Field(
        "{}", title="Online Store (JSON)",
        description="Online store object with the fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeleteOnlineStoreConfig(BaseModel):
    """Delete an online store by name."""
    operation: Literal["delete_online_store"] = Field(
        "delete_online_store",
        json_schema_extra={"const": "delete_online_store", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Delete Online Store"},
        title="Delete Online Store",
    )
    name: str = Field(..., title="Online Store Name", description="Name of the online store to delete.")


class DatabricksListFeaturesConfig(BaseModel):
    """List all features in the feature engineering registry."""
    operation: Literal["list_features"] = Field(
        "list_features",
        json_schema_extra={"const": "list_features", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "List Features"},
        title="List Features",
    )
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token returned by a previous list call.")


class DatabricksCreateFeatureConfig(BaseModel):
    """Create a new feature."""
    operation: Literal["create_feature"] = Field(
        "create_feature",
        json_schema_extra={"const": "create_feature", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Create Feature"},
        title="Create Feature",
    )
    feature_json: str = Field(
        "{}", title="Feature (JSON)",
        description="Full feature object (full_name, source, function, inputs, etc).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksGetFeatureConfig(BaseModel):
    """Get a feature by its full name."""
    operation: Literal["get_feature"] = Field(
        "get_feature",
        json_schema_extra={"const": "get_feature", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Get Feature"},
        title="Get Feature",
    )
    full_name: str = Field(..., title="Feature Full Name", description="Three-level full name of the feature (catalog.schema.feature).")


class DatabricksUpdateFeatureConfig(BaseModel):
    """Update an existing feature."""
    operation: Literal["update_feature"] = Field(
        "update_feature",
        json_schema_extra={"const": "update_feature", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Update Feature"},
        title="Update Feature",
    )
    full_name: str = Field(..., title="Feature Full Name", description="Three-level full name of the feature (catalog.schema.feature).")
    update_mask: str = Field(..., title="Update Mask", description="Comma-separated list of fields to update.")
    feature_json: str = Field(
        "{}", title="Feature (JSON)",
        description="Feature object with the fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DatabricksDeleteFeatureConfig(BaseModel):
    """Delete a feature by its full name."""
    operation: Literal["delete_feature"] = Field(
        "delete_feature",
        json_schema_extra={"const": "delete_feature", "ui:hidden": True,
                           "x-category": "Feature Store", "x-is-trigger": False,
                           "x-display-name": "Delete Feature"},
        title="Delete Feature",
    )
    full_name: str = Field(..., title="Feature Full Name", description="Three-level full name of the feature (catalog.schema.feature).")


async def _list_online_stores(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/feature-store/online-stores",
        params={"page_token": c.page_token}, action_name="list_online_stores",
    )


async def _create_online_store(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.online_store_json, "Online Store") or {}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/feature-store/online-stores",
        json_body=body, action_name="create_online_store",
    )


async def _get_online_store(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/feature-store/online-stores/{c.name}",
        action_name="get_online_store",
    )


async def _update_online_store(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.online_store_json, "Online Store") or {}
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.0/feature-store/online-stores/{c.name}",
        params={"update_mask": c.update_mask}, json_body=body,
        action_name="update_online_store",
    )


async def _delete_online_store(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/feature-store/online-stores/{c.name}",
        action_name="delete_online_store",
    )


async def _list_features(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/feature-engineering/features",
        params={"page_token": c.page_token}, action_name="list_features",
    )


async def _create_feature(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.feature_json, "Feature") or {}
    return await _databricks_request(
        host, token, "POST", "/api/2.0/feature-engineering/features",
        json_body=body, action_name="create_feature",
    )


async def _get_feature(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/feature-engineering/features/{c.full_name}",
        action_name="get_feature",
    )


async def _update_feature(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.feature_json, "Feature") or {}
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.0/feature-engineering/features/{c.full_name}",
        params={"update_mask": c.update_mask}, json_body=body,
        action_name="update_feature",
    )


async def _delete_feature(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/feature-engineering/features/{c.full_name}",
        action_name="delete_feature",
    )


OPERATION_CONFIGS.extend([
    DatabricksListOnlineStoresConfig,
    DatabricksCreateOnlineStoreConfig,
    DatabricksGetOnlineStoreConfig,
    DatabricksUpdateOnlineStoreConfig,
    DatabricksDeleteOnlineStoreConfig,
    DatabricksListFeaturesConfig,
    DatabricksCreateFeatureConfig,
    DatabricksGetFeatureConfig,
    DatabricksUpdateFeatureConfig,
    DatabricksDeleteFeatureConfig,
])
OPERATION_HANDLERS.update({
    "list_online_stores": _list_online_stores,
    "create_online_store": _create_online_store,
    "get_online_store": _get_online_store,
    "update_online_store": _update_online_store,
    "delete_online_store": _delete_online_store,
    "list_features": _list_features,
    "create_feature": _create_feature,
    "get_feature": _get_feature,
    "update_feature": _update_feature,
    "delete_feature": _delete_feature,
})


# ---- Identity (19 ops) ----
class DatabricksGetCurrentUserConfig(BaseModel):
    """Get the SCIM details of the currently authenticated user."""
    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={"const": "get_current_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Get Current User"},
        title="Get Current User",
    )


async def _get_current_user(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/preview/scim/v2/Me",
                                     action_name="get_current_user", content_type="application/scim+json")


class DatabricksListUsersConfig(BaseModel):
    """List users in the workspace via SCIM."""
    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={"const": "list_users", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "List Users"},
        title="List Users",
    )
    filter: Optional[str] = Field(None, title="Filter", description="SCIM filter expression, e.g. userName eq \"user@example.com\".")
    startIndex: Optional[str] = Field(None, title="Start Index", description="1-based index of the first result to return.")
    count: Optional[str] = Field(None, title="Count", description="Desired number of results per page.")
    attributes: Optional[str] = Field(None, title="Attributes", description="Comma-separated list of attributes to return.")
    sortBy: Optional[str] = Field(None, title="Sort By", description="Attribute to sort results by.")


async def _list_users(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/preview/scim/v2/Users",
                                     params={"filter": c.filter, "startIndex": c.startIndex,
                                             "count": c.count, "attributes": c.attributes,
                                             "sortBy": c.sortBy},
                                     action_name="list_users", content_type="application/scim+json")


class DatabricksCreateUserConfig(BaseModel):
    """Create a new user via SCIM."""
    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={"const": "create_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Create User"},
        title="Create User",
    )
    user_json: str = Field(
        "{}", title="User (JSON)",
        description="Full SCIM user object (userName, name, emails, entitlements, etc).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_user(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.user_json, "User") or {}
    return await _databricks_request(host, token, "POST", "/api/2.0/preview/scim/v2/Users",
                                     json_body=body, action_name="create_user",
                                     content_type="application/scim+json")


class DatabricksGetUserConfig(BaseModel):
    """Get a user by SCIM id."""
    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={"const": "get_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Get User"},
        title="Get User",
    )
    user_id: str = Field(..., title="User ID", description="SCIM id of the user.")


async def _get_user(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/preview/scim/v2/Users/{c.user_id}",
                                     action_name="get_user", content_type="application/scim+json")


class DatabricksUpdateUserConfig(BaseModel):
    """Replace a user via SCIM (PUT)."""
    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={"const": "update_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Update User"},
        title="Update User",
    )
    user_id: str = Field(..., title="User ID", description="SCIM id of the user to replace.")
    user_json: str = Field(
        "{}", title="User (JSON)",
        description="Full SCIM user object to overwrite the existing user with.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_user(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.user_json, "User") or {}
    return await _databricks_request(host, token, "PUT", f"/api/2.0/preview/scim/v2/Users/{c.user_id}",
                                     json_body=body, action_name="update_user",
                                     content_type="application/scim+json")


class DatabricksPatchUserConfig(BaseModel):
    """Partially update a user via SCIM PatchOp."""
    operation: Literal["patch_user"] = Field(
        "patch_user",
        json_schema_extra={"const": "patch_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Patch User"},
        title="Patch User",
    )
    user_id: str = Field(..., title="User ID", description="SCIM id of the user to patch.")
    operations_json: str = Field(
        "[]", title="Operations (JSON)",
        description="Array of SCIM PatchOp operations (op, path, value).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _patch_user(c, host, token) -> Dict[str, Any]:
    ops = _parse_json_field(c.operations_json, "Operations") or []
    body = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": ops}
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/preview/scim/v2/Users/{c.user_id}",
                                     json_body=body, action_name="patch_user",
                                     content_type="application/scim+json")


class DatabricksDeleteUserConfig(BaseModel):
    """Delete a user by SCIM id."""
    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={"const": "delete_user", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Delete User"},
        title="Delete User",
    )
    user_id: str = Field(..., title="User ID", description="SCIM id of the user to delete.")


async def _delete_user(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/preview/scim/v2/Users/{c.user_id}",
                                     action_name="delete_user", content_type="application/scim+json")


class DatabricksListGroupsConfig(BaseModel):
    """List groups in the workspace via SCIM."""
    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={"const": "list_groups", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "List Groups"},
        title="List Groups",
    )
    filter: Optional[str] = Field(None, title="Filter", description="SCIM filter expression, e.g. displayName eq \"admins\".")
    startIndex: Optional[str] = Field(None, title="Start Index", description="1-based index of the first result to return.")
    count: Optional[str] = Field(None, title="Count", description="Desired number of results per page.")


async def _list_groups(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/preview/scim/v2/Groups",
                                     params={"filter": c.filter, "startIndex": c.startIndex,
                                             "count": c.count},
                                     action_name="list_groups", content_type="application/scim+json")


class DatabricksCreateGroupConfig(BaseModel):
    """Create a new group via SCIM."""
    operation: Literal["create_group"] = Field(
        "create_group",
        json_schema_extra={"const": "create_group", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Create Group"},
        title="Create Group",
    )
    group_json: str = Field(
        "{}", title="Group (JSON)",
        description="Full SCIM group object (displayName, members, entitlements).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_group(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.group_json, "Group") or {}
    return await _databricks_request(host, token, "POST", "/api/2.0/preview/scim/v2/Groups",
                                     json_body=body, action_name="create_group",
                                     content_type="application/scim+json")


class DatabricksGetGroupConfig(BaseModel):
    """Get a group by SCIM id."""
    operation: Literal["get_group"] = Field(
        "get_group",
        json_schema_extra={"const": "get_group", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Get Group"},
        title="Get Group",
    )
    group_id: str = Field(..., title="Group ID", description="SCIM id of the group.")


async def _get_group(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/preview/scim/v2/Groups/{c.group_id}",
                                     action_name="get_group", content_type="application/scim+json")


class DatabricksUpdateGroupConfig(BaseModel):
    """Replace a group via SCIM (PUT)."""
    operation: Literal["update_group"] = Field(
        "update_group",
        json_schema_extra={"const": "update_group", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Update Group"},
        title="Update Group",
    )
    group_id: str = Field(..., title="Group ID", description="SCIM id of the group to replace.")
    group_json: str = Field(
        "{}", title="Group (JSON)",
        description="Full SCIM group object to overwrite the existing group with.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_group(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.group_json, "Group") or {}
    return await _databricks_request(host, token, "PUT", f"/api/2.0/preview/scim/v2/Groups/{c.group_id}",
                                     json_body=body, action_name="update_group",
                                     content_type="application/scim+json")


class DatabricksPatchGroupConfig(BaseModel):
    """Partially update a group via SCIM PatchOp."""
    operation: Literal["patch_group"] = Field(
        "patch_group",
        json_schema_extra={"const": "patch_group", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Patch Group"},
        title="Patch Group",
    )
    group_id: str = Field(..., title="Group ID", description="SCIM id of the group to patch.")
    operations_json: str = Field(
        "[]", title="Operations (JSON)",
        description="Array of SCIM PatchOp operations (op, path, value).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _patch_group(c, host, token) -> Dict[str, Any]:
    ops = _parse_json_field(c.operations_json, "Operations") or []
    body = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": ops}
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/preview/scim/v2/Groups/{c.group_id}",
                                     json_body=body, action_name="patch_group",
                                     content_type="application/scim+json")


class DatabricksDeleteGroupConfig(BaseModel):
    """Delete a group by SCIM id."""
    operation: Literal["delete_group"] = Field(
        "delete_group",
        json_schema_extra={"const": "delete_group", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Delete Group"},
        title="Delete Group",
    )
    group_id: str = Field(..., title="Group ID", description="SCIM id of the group to delete.")


async def _delete_group(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/preview/scim/v2/Groups/{c.group_id}",
                                     action_name="delete_group", content_type="application/scim+json")


class DatabricksListServicePrincipalsConfig(BaseModel):
    """List service principals in the workspace via SCIM."""
    operation: Literal["list_service_principals"] = Field(
        "list_service_principals",
        json_schema_extra={"const": "list_service_principals", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "List Service Principals"},
        title="List Service Principals",
    )
    filter: Optional[str] = Field(None, title="Filter", description="SCIM filter expression, e.g. displayName eq \"my-sp\".")
    startIndex: Optional[str] = Field(None, title="Start Index", description="1-based index of the first result to return.")
    count: Optional[str] = Field(None, title="Count", description="Desired number of results per page.")


async def _list_service_principals(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/preview/scim/v2/ServicePrincipals",
                                     params={"filter": c.filter, "startIndex": c.startIndex,
                                             "count": c.count},
                                     action_name="list_service_principals",
                                     content_type="application/scim+json")


class DatabricksCreateServicePrincipalConfig(BaseModel):
    """Create a new service principal via SCIM."""
    operation: Literal["create_service_principal"] = Field(
        "create_service_principal",
        json_schema_extra={"const": "create_service_principal", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Create Service Principal"},
        title="Create Service Principal",
    )
    service_principal_json: str = Field(
        "{}", title="Service Principal (JSON)",
        description="Full SCIM service principal object (applicationId, displayName, entitlements).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_service_principal(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.service_principal_json, "Service Principal") or {}
    return await _databricks_request(host, token, "POST", "/api/2.0/preview/scim/v2/ServicePrincipals",
                                     json_body=body, action_name="create_service_principal",
                                     content_type="application/scim+json")


class DatabricksGetServicePrincipalConfig(BaseModel):
    """Get a service principal by SCIM id."""
    operation: Literal["get_service_principal"] = Field(
        "get_service_principal",
        json_schema_extra={"const": "get_service_principal", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Get Service Principal"},
        title="Get Service Principal",
    )
    service_principal_id: str = Field(..., title="Service Principal ID", description="SCIM id of the service principal.")


async def _get_service_principal(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET",
                                     f"/api/2.0/preview/scim/v2/ServicePrincipals/{c.service_principal_id}",
                                     action_name="get_service_principal",
                                     content_type="application/scim+json")


class DatabricksUpdateServicePrincipalConfig(BaseModel):
    """Replace a service principal via SCIM (PUT)."""
    operation: Literal["update_service_principal"] = Field(
        "update_service_principal",
        json_schema_extra={"const": "update_service_principal", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Update Service Principal"},
        title="Update Service Principal",
    )
    service_principal_id: str = Field(..., title="Service Principal ID", description="SCIM id of the service principal to replace.")
    service_principal_json: str = Field(
        "{}", title="Service Principal (JSON)",
        description="Full SCIM service principal object to overwrite the existing one with.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_service_principal(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.service_principal_json, "Service Principal") or {}
    return await _databricks_request(host, token, "PUT",
                                     f"/api/2.0/preview/scim/v2/ServicePrincipals/{c.service_principal_id}",
                                     json_body=body, action_name="update_service_principal",
                                     content_type="application/scim+json")


class DatabricksPatchServicePrincipalConfig(BaseModel):
    """Partially update a service principal via SCIM PatchOp."""
    operation: Literal["patch_service_principal"] = Field(
        "patch_service_principal",
        json_schema_extra={"const": "patch_service_principal", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Patch Service Principal"},
        title="Patch Service Principal",
    )
    service_principal_id: str = Field(..., title="Service Principal ID", description="SCIM id of the service principal to patch.")
    operations_json: str = Field(
        "[]", title="Operations (JSON)",
        description="Array of SCIM PatchOp operations (op, path, value).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _patch_service_principal(c, host, token) -> Dict[str, Any]:
    ops = _parse_json_field(c.operations_json, "Operations") or []
    body = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": ops}
    return await _databricks_request(host, token, "PATCH",
                                     f"/api/2.0/preview/scim/v2/ServicePrincipals/{c.service_principal_id}",
                                     json_body=body, action_name="patch_service_principal",
                                     content_type="application/scim+json")


class DatabricksDeleteServicePrincipalConfig(BaseModel):
    """Delete a service principal by SCIM id."""
    operation: Literal["delete_service_principal"] = Field(
        "delete_service_principal",
        json_schema_extra={"const": "delete_service_principal", "ui:hidden": True,
                           "x-category": "Identity", "x-is-trigger": False,
                           "x-display-name": "Delete Service Principal"},
        title="Delete Service Principal",
    )
    service_principal_id: str = Field(..., title="Service Principal ID", description="SCIM id of the service principal to delete.")


async def _delete_service_principal(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE",
                                     f"/api/2.0/preview/scim/v2/ServicePrincipals/{c.service_principal_id}",
                                     action_name="delete_service_principal",
                                     content_type="application/scim+json")


OPERATION_CONFIGS.extend([
    DatabricksGetCurrentUserConfig, DatabricksListUsersConfig, DatabricksCreateUserConfig,
    DatabricksGetUserConfig, DatabricksUpdateUserConfig, DatabricksPatchUserConfig,
    DatabricksDeleteUserConfig, DatabricksListGroupsConfig, DatabricksCreateGroupConfig,
    DatabricksGetGroupConfig, DatabricksUpdateGroupConfig, DatabricksPatchGroupConfig,
    DatabricksDeleteGroupConfig, DatabricksListServicePrincipalsConfig,
    DatabricksCreateServicePrincipalConfig, DatabricksGetServicePrincipalConfig,
    DatabricksUpdateServicePrincipalConfig, DatabricksPatchServicePrincipalConfig,
    DatabricksDeleteServicePrincipalConfig,
])
OPERATION_HANDLERS.update({
    "get_current_user": _get_current_user,
    "list_users": _list_users,
    "create_user": _create_user,
    "get_user": _get_user,
    "update_user": _update_user,
    "patch_user": _patch_user,
    "delete_user": _delete_user,
    "list_groups": _list_groups,
    "create_group": _create_group,
    "get_group": _get_group,
    "update_group": _update_group,
    "patch_group": _patch_group,
    "delete_group": _delete_group,
    "list_service_principals": _list_service_principals,
    "create_service_principal": _create_service_principal,
    "get_service_principal": _get_service_principal,
    "update_service_principal": _update_service_principal,
    "patch_service_principal": _patch_service_principal,
    "delete_service_principal": _delete_service_principal,
})


# ---- Access Control (21 ops) ----
class DatabricksGetPermissionLevelsConfig(BaseModel):
    """Get the permission levels a user can have on an object."""
    operation: Literal["get_permission_levels"] = Field(
        "get_permission_levels",
        json_schema_extra={"const": "get_permission_levels", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Get Permission Levels"},
        title="Get Permission Levels",
    )
    object_type: str = Field(..., title="Object Type", description="Type of the object (e.g. clusters, jobs, warehouses, notebooks, directories, registered-models, experiments).")
    object_id: str = Field(..., title="Object ID", description="ID of the object to inspect.")


async def _get_permission_levels(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/permissions/{c.object_type}/{c.object_id}/permissionLevels", action_name="get_permission_levels")


class DatabricksGetObjectPermissionsConfig(BaseModel):
    """Get the permissions set on an object."""
    operation: Literal["get_object_permissions"] = Field(
        "get_object_permissions",
        json_schema_extra={"const": "get_object_permissions", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Get Object Permissions"},
        title="Get Object Permissions",
    )
    object_type: str = Field(..., title="Object Type", description="Type of the object (e.g. clusters, jobs, warehouses, notebooks, directories).")
    object_id: str = Field(..., title="Object ID", description="ID of the object.")


async def _get_object_permissions(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/permissions/{c.object_type}/{c.object_id}", action_name="get_object_permissions")


class DatabricksSetObjectPermissionsConfig(BaseModel):
    """Set (overwrite) the permissions on an object."""
    operation: Literal["set_object_permissions"] = Field(
        "set_object_permissions",
        json_schema_extra={"const": "set_object_permissions", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Set Object Permissions"},
        title="Set Object Permissions",
    )
    object_type: str = Field(..., title="Object Type", description="Type of the object (e.g. clusters, jobs, warehouses).")
    object_id: str = Field(..., title="Object ID", description="ID of the object.")
    access_control_list_json: str = Field(
        "[]", title="Access Control List (JSON)",
        description="JSON array of access control entries, e.g. [{\"user_name\":\"me@x.com\",\"permission_level\":\"CAN_MANAGE\"}].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _set_object_permissions(c, host, token) -> Dict[str, Any]:
    acl = _parse_json_field(c.access_control_list_json, "Access Control List") or []
    return await _databricks_request(host, token, "PUT", f"/api/2.0/permissions/{c.object_type}/{c.object_id}", json_body={"access_control_list": acl}, action_name="set_object_permissions")


class DatabricksUpdateObjectPermissionsConfig(BaseModel):
    """Update (merge) the permissions on an object."""
    operation: Literal["update_object_permissions"] = Field(
        "update_object_permissions",
        json_schema_extra={"const": "update_object_permissions", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Update Object Permissions"},
        title="Update Object Permissions",
    )
    object_type: str = Field(..., title="Object Type", description="Type of the object (e.g. clusters, jobs, warehouses).")
    object_id: str = Field(..., title="Object ID", description="ID of the object.")
    access_control_list_json: str = Field(
        "[]", title="Access Control List (JSON)",
        description="JSON array of access control entries to merge, e.g. [{\"group_name\":\"admins\",\"permission_level\":\"CAN_MANAGE\"}].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_object_permissions(c, host, token) -> Dict[str, Any]:
    acl = _parse_json_field(c.access_control_list_json, "Access Control List") or []
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/permissions/{c.object_type}/{c.object_id}", json_body={"access_control_list": acl}, action_name="update_object_permissions")


class DatabricksListPermissionAssignmentsConfig(BaseModel):
    """List workspace permission assignments for all principals."""
    operation: Literal["list_permission_assignments"] = Field(
        "list_permission_assignments",
        json_schema_extra={"const": "list_permission_assignments", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "List Permission Assignments"},
        title="List Permission Assignments",
    )


async def _list_permission_assignments(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/preview/permissionassignments", action_name="list_permission_assignments")


class DatabricksCreatePermissionAssignmentConfig(BaseModel):
    """Create or update a workspace permission assignment for a principal."""
    operation: Literal["create_permission_assignment"] = Field(
        "create_permission_assignment",
        json_schema_extra={"const": "create_permission_assignment", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Create Permission Assignment"},
        title="Create Permission Assignment",
    )
    principal_id: str = Field(..., title="Principal ID", description="ID of the principal (user, group, or service principal).")
    permissions_json: str = Field(
        "[]", title="Permissions (JSON)",
        description="JSON array of workspace permissions, e.g. [\"USER\"] or [\"ADMIN\"].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_permission_assignment(c, host, token) -> Dict[str, Any]:
    perms = _parse_json_field(c.permissions_json, "Permissions") or []
    return await _databricks_request(host, token, "PUT", f"/api/2.0/preview/permissionassignments/principals/{c.principal_id}", json_body={"permissions": perms}, action_name="create_permission_assignment")


class DatabricksDeletePermissionAssignmentConfig(BaseModel):
    """Delete a workspace permission assignment for a principal."""
    operation: Literal["delete_permission_assignment"] = Field(
        "delete_permission_assignment",
        json_schema_extra={"const": "delete_permission_assignment", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Delete Permission Assignment"},
        title="Delete Permission Assignment",
    )
    principal_id: str = Field(..., title="Principal ID", description="ID of the principal whose assignment is removed.")


async def _delete_permission_assignment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/preview/permissionassignments/principals/{c.principal_id}", action_name="delete_permission_assignment")


class DatabricksCreateTokenConfig(BaseModel):
    """Create a personal access token."""
    operation: Literal["create_token"] = Field(
        "create_token",
        json_schema_extra={"const": "create_token", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Create Token"},
        title="Create Token",
    )
    comment: Optional[str] = Field(None, title="Comment", description="Optional description for the token.")
    lifetime_seconds: Optional[int] = Field(None, title="Lifetime (seconds)", description="Token lifetime in seconds. Omit for no expiration.")


async def _create_token(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/token/create", json_body={"comment": c.comment, "lifetime_seconds": c.lifetime_seconds}, action_name="create_token")


class DatabricksListTokensConfig(BaseModel):
    """List personal access tokens for the calling user."""
    operation: Literal["list_tokens"] = Field(
        "list_tokens",
        json_schema_extra={"const": "list_tokens", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "List Tokens"},
        title="List Tokens",
    )


async def _list_tokens(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/token/list", action_name="list_tokens")


class DatabricksDeleteTokenConfig(BaseModel):
    """Revoke a personal access token."""
    operation: Literal["delete_token"] = Field(
        "delete_token",
        json_schema_extra={"const": "delete_token", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Delete Token"},
        title="Delete Token",
    )
    token_id: str = Field(..., title="Token ID", description="ID of the token to revoke.")


async def _delete_token(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/token/delete", json_body={"token_id": c.token_id}, action_name="delete_token")


class DatabricksListTokenManagementConfig(BaseModel):
    """List all tokens in the workspace (admin token management)."""
    operation: Literal["list_token_management"] = Field(
        "list_token_management",
        json_schema_extra={"const": "list_token_management", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "List Managed Tokens"},
        title="List Managed Tokens",
    )
    created_by_id: Optional[str] = Field(None, title="Created By ID", description="Filter tokens by the user ID that created them.")
    created_by_username: Optional[str] = Field(None, title="Created By Username", description="Filter tokens by the username that created them.")


async def _list_token_management(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/token-management/tokens", params={"created_by_id": c.created_by_id, "created_by_username": c.created_by_username}, action_name="list_token_management")


class DatabricksGetTokenManagementConfig(BaseModel):
    """Get details of a managed token by ID."""
    operation: Literal["get_token_management"] = Field(
        "get_token_management",
        json_schema_extra={"const": "get_token_management", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Get Managed Token"},
        title="Get Managed Token",
    )
    token_id: str = Field(..., title="Token ID", description="ID of the managed token.")


async def _get_token_management(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/token-management/tokens/{c.token_id}", action_name="get_token_management")


class DatabricksDeleteTokenManagementConfig(BaseModel):
    """Delete a managed token by ID (admin token management)."""
    operation: Literal["delete_token_management"] = Field(
        "delete_token_management",
        json_schema_extra={"const": "delete_token_management", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Delete Managed Token"},
        title="Delete Managed Token",
    )
    token_id: str = Field(..., title="Token ID", description="ID of the managed token to delete.")


async def _delete_token_management(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/token-management/tokens/{c.token_id}", action_name="delete_token_management")


class DatabricksCreateOboTokenConfig(BaseModel):
    """Create an on-behalf-of token for a service principal."""
    operation: Literal["create_obo_token"] = Field(
        "create_obo_token",
        json_schema_extra={"const": "create_obo_token", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Create On-Behalf-Of Token"},
        title="Create On-Behalf-Of Token",
    )
    application_id: str = Field(..., title="Application ID", description="Application ID of the service principal to mint the token for.")
    comment: Optional[str] = Field(None, title="Comment", description="Optional description for the token.")
    lifetime_seconds: Optional[int] = Field(None, title="Lifetime (seconds)", description="Token lifetime in seconds. Omit for no expiration.")


async def _create_obo_token(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", "/api/2.0/token-management/on-behalf-of/tokens", json_body={"application_id": c.application_id, "comment": c.comment, "lifetime_seconds": c.lifetime_seconds}, action_name="create_obo_token")


class DatabricksListIpAccessListsConfig(BaseModel):
    """List all IP access lists for the workspace."""
    operation: Literal["list_ip_access_lists"] = Field(
        "list_ip_access_lists",
        json_schema_extra={"const": "list_ip_access_lists", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "List IP Access Lists"},
        title="List IP Access Lists",
    )


async def _list_ip_access_lists(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/ip-access-lists", action_name="list_ip_access_lists")


class DatabricksCreateIpAccessListConfig(BaseModel):
    """Create an IP access list."""
    operation: Literal["create_ip_access_list"] = Field(
        "create_ip_access_list",
        json_schema_extra={"const": "create_ip_access_list", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Create IP Access List"},
        title="Create IP Access List",
    )
    label: str = Field(..., title="Label", description="Label for the IP access list.")
    list_type: str = Field(
        "ALLOW", title="List Type", description="Whether this list allows or blocks the specified IPs.",
        json_schema_extra={"enum": ["ALLOW", "BLOCK"], "enumNames": ["Allow", "Block"], "x-enum-searchable": True},
    )
    ip_addresses_json: str = Field(
        "[]", title="IP Addresses (JSON)",
        description="JSON array of IP addresses or CIDR ranges, e.g. [\"1.2.3.4\",\"10.0.0.0/16\"].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_ip_access_list(c, host, token) -> Dict[str, Any]:
    ips = _parse_json_field(c.ip_addresses_json, "IP Addresses") or []
    return await _databricks_request(host, token, "POST", "/api/2.0/ip-access-lists", json_body={"label": c.label, "list_type": c.list_type, "ip_addresses": ips}, action_name="create_ip_access_list")


class DatabricksGetIpAccessListConfig(BaseModel):
    """Get a single IP access list by ID."""
    operation: Literal["get_ip_access_list"] = Field(
        "get_ip_access_list",
        json_schema_extra={"const": "get_ip_access_list", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Get IP Access List"},
        title="Get IP Access List",
    )
    ip_access_list_id: str = Field(..., title="IP Access List ID", description="ID of the IP access list.")


async def _get_ip_access_list(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/ip-access-lists/{c.ip_access_list_id}", action_name="get_ip_access_list")


class DatabricksUpdateIpAccessListConfig(BaseModel):
    """Replace (update) an existing IP access list."""
    operation: Literal["update_ip_access_list"] = Field(
        "update_ip_access_list",
        json_schema_extra={"const": "update_ip_access_list", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Update IP Access List"},
        title="Update IP Access List",
    )
    ip_access_list_id: str = Field(..., title="IP Access List ID", description="ID of the IP access list to update.")
    label: Optional[str] = Field(None, title="Label", description="New label for the IP access list.")
    list_type: Optional[str] = Field(
        None, title="List Type", description="Whether this list allows or blocks the specified IPs.",
        json_schema_extra={"enum": ["ALLOW", "BLOCK"], "enumNames": ["Allow", "Block"], "x-enum-searchable": True},
    )
    ip_addresses_json: str = Field(
        "[]", title="IP Addresses (JSON)",
        description="JSON array of IP addresses or CIDR ranges to set on the list.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    enabled: str = Field(
        "true", title="Enabled", description="Whether the IP access list is enabled.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _update_ip_access_list(c, host, token) -> Dict[str, Any]:
    ips = _parse_json_field(c.ip_addresses_json, "IP Addresses")
    return await _databricks_request(host, token, "PUT", f"/api/2.0/ip-access-lists/{c.ip_access_list_id}", json_body={"label": c.label, "list_type": c.list_type, "ip_addresses": ips, "enabled": c.enabled == "true"}, action_name="update_ip_access_list")


class DatabricksDeleteIpAccessListConfig(BaseModel):
    """Delete an IP access list by ID."""
    operation: Literal["delete_ip_access_list"] = Field(
        "delete_ip_access_list",
        json_schema_extra={"const": "delete_ip_access_list", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Delete IP Access List"},
        title="Delete IP Access List",
    )
    ip_access_list_id: str = Field(..., title="IP Access List ID", description="ID of the IP access list to delete.")


async def _delete_ip_access_list(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/ip-access-lists/{c.ip_access_list_id}", action_name="delete_ip_access_list")


class DatabricksGetWorkspaceConfConfig(BaseModel):
    """Get workspace configuration values for the given keys."""
    operation: Literal["get_workspace_conf"] = Field(
        "get_workspace_conf",
        json_schema_extra={"const": "get_workspace_conf", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Get Workspace Configuration"},
        title="Get Workspace Configuration",
    )
    keys: str = Field(..., title="Keys", description="Comma-separated configuration keys to read, e.g. enableTokensConfig.")


async def _get_workspace_conf(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/workspace-conf", params={"keys": c.keys}, action_name="get_workspace_conf")


class DatabricksSetWorkspaceConfConfig(BaseModel):
    """Set (patch) workspace configuration values."""
    operation: Literal["set_workspace_conf"] = Field(
        "set_workspace_conf",
        json_schema_extra={"const": "set_workspace_conf", "ui:hidden": True,
                           "x-category": "Access Control", "x-is-trigger": False,
                           "x-display-name": "Set Workspace Configuration"},
        title="Set Workspace Configuration",
    )
    conf_json: str = Field(
        "{}", title="Configuration (JSON)",
        description="JSON object of key/value config settings, e.g. {\"enableTokensConfig\":\"true\"}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _set_workspace_conf(c, host, token) -> Dict[str, Any]:
    conf = _parse_json_field(c.conf_json, "Configuration") or {}
    return await _databricks_request(host, token, "PATCH", "/api/2.0/workspace-conf", json_body=conf, action_name="set_workspace_conf")


OPERATION_CONFIGS.extend([
    DatabricksGetPermissionLevelsConfig,
    DatabricksGetObjectPermissionsConfig,
    DatabricksSetObjectPermissionsConfig,
    DatabricksUpdateObjectPermissionsConfig,
    DatabricksListPermissionAssignmentsConfig,
    DatabricksCreatePermissionAssignmentConfig,
    DatabricksDeletePermissionAssignmentConfig,
    DatabricksCreateTokenConfig,
    DatabricksListTokensConfig,
    DatabricksDeleteTokenConfig,
    DatabricksListTokenManagementConfig,
    DatabricksGetTokenManagementConfig,
    DatabricksDeleteTokenManagementConfig,
    DatabricksCreateOboTokenConfig,
    DatabricksListIpAccessListsConfig,
    DatabricksCreateIpAccessListConfig,
    DatabricksGetIpAccessListConfig,
    DatabricksUpdateIpAccessListConfig,
    DatabricksDeleteIpAccessListConfig,
    DatabricksGetWorkspaceConfConfig,
    DatabricksSetWorkspaceConfConfig,
])
OPERATION_HANDLERS.update({
    "get_permission_levels": _get_permission_levels,
    "get_object_permissions": _get_object_permissions,
    "set_object_permissions": _set_object_permissions,
    "update_object_permissions": _update_object_permissions,
    "list_permission_assignments": _list_permission_assignments,
    "create_permission_assignment": _create_permission_assignment,
    "delete_permission_assignment": _delete_permission_assignment,
    "create_token": _create_token,
    "list_tokens": _list_tokens,
    "delete_token": _delete_token,
    "list_token_management": _list_token_management,
    "get_token_management": _get_token_management,
    "delete_token_management": _delete_token_management,
    "create_obo_token": _create_obo_token,
    "list_ip_access_lists": _list_ip_access_lists,
    "create_ip_access_list": _create_ip_access_list,
    "get_ip_access_list": _get_ip_access_list,
    "update_ip_access_list": _update_ip_access_list,
    "delete_ip_access_list": _delete_ip_access_list,
    "get_workspace_conf": _get_workspace_conf,
    "set_workspace_conf": _set_workspace_conf,
})


# ---- Apps (10 ops) ----
class DatabricksListAppsConfig(BaseModel):
    """List all Databricks Apps in the workspace."""
    operation: Literal["list_apps"] = Field(
        "list_apps",
        json_schema_extra={"const": "list_apps", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "List Apps"},
        title="List Apps",
    )
    page_size: Optional[str] = Field(None, title="Page Size", description="Upper bound for the number of apps to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token to go to the next page of apps.")


async def _list_apps(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", "/api/2.0/apps", params={"page_size": c.page_size, "page_token": c.page_token}, action_name="list_apps")


class DatabricksCreateAppConfig(BaseModel):
    """Create a new Databricks App."""
    operation: Literal["create_app"] = Field(
        "create_app",
        json_schema_extra={"const": "create_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Create App"},
        title="Create App",
    )
    name: str = Field(..., title="App Name", description="The name of the app (unique within the workspace).")
    description: Optional[str] = Field(None, title="Description", description="Optional description of the app.")
    no_compute: str = Field("false", title="No Compute", description="If true, the app is created without provisioning compute.", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    app_json: str = Field("{}", title="App Spec (JSON)", description="Additional app fields such as resources[], user_api_scopes[]. Merged into the request body.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_app(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.app_json, "App Spec") or {}
    body["name"] = c.name
    if c.description is not None:
        body["description"] = c.description
    params = {"no_compute": "true"} if c.no_compute == "true" else {}
    return await _databricks_request(host, token, "POST", "/api/2.0/apps", params=params, json_body=body, action_name="create_app")


class DatabricksGetAppConfig(BaseModel):
    """Get details of a Databricks App by name."""
    operation: Literal["get_app"] = Field(
        "get_app",
        json_schema_extra={"const": "get_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Get App"},
        title="Get App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to retrieve.")


async def _get_app(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/apps/{c.name}", action_name="get_app")


class DatabricksUpdateAppConfig(BaseModel):
    """Update a Databricks App."""
    operation: Literal["update_app"] = Field(
        "update_app",
        json_schema_extra={"const": "update_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Update App"},
        title="Update App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to update.")
    description: Optional[str] = Field(None, title="Description", description="Updated description of the app.")
    update_mask: Optional[str] = Field(None, title="Update Mask", description="Comma-separated list of fields to update (e.g. 'description,resources').")
    app_json: str = Field("{}", title="App Spec (JSON)", description="Additional app fields such as resources[]. Merged into the request body.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_app(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.app_json, "App Spec") or {}
    body["name"] = c.name
    if c.description is not None:
        body["description"] = c.description
    return await _databricks_request(host, token, "PATCH", f"/api/2.0/apps/{c.name}", params={"update_mask": c.update_mask}, json_body=body, action_name="update_app")


class DatabricksDeleteAppConfig(BaseModel):
    """Delete a Databricks App by name."""
    operation: Literal["delete_app"] = Field(
        "delete_app",
        json_schema_extra={"const": "delete_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Delete App"},
        title="Delete App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to delete.")


async def _delete_app(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "DELETE", f"/api/2.0/apps/{c.name}", action_name="delete_app")


class DatabricksStartAppConfig(BaseModel):
    """Start a Databricks App."""
    operation: Literal["start_app"] = Field(
        "start_app",
        json_schema_extra={"const": "start_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Start App"},
        title="Start App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to start.")


async def _start_app(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.0/apps/{c.name}/start", json_body={}, action_name="start_app")


class DatabricksStopAppConfig(BaseModel):
    """Stop a Databricks App."""
    operation: Literal["stop_app"] = Field(
        "stop_app",
        json_schema_extra={"const": "stop_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Stop App"},
        title="Stop App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to stop.")


async def _stop_app(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "POST", f"/api/2.0/apps/{c.name}/stop", json_body={}, action_name="stop_app")


class DatabricksDeployAppConfig(BaseModel):
    """Create a new deployment for a Databricks App."""
    operation: Literal["deploy_app"] = Field(
        "deploy_app",
        json_schema_extra={"const": "deploy_app", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Deploy App"},
        title="Deploy App",
    )
    name: str = Field(..., title="App Name", description="The name of the app to deploy.")
    source_code_path: Optional[str] = Field(None, title="Source Code Path", description="Workspace file system path of the source code used to create the deployment.")
    mode: Optional[str] = Field(None, title="Deployment Mode", description="The mode of the deployment.", json_schema_extra={"enum": ["SNAPSHOT", "AUTO_SYNC"], "enumNames": ["Snapshot", "Auto Sync"], "x-enum-searchable": True})
    deployment_json: str = Field("{}", title="Deployment Spec (JSON)", description="Additional deployment fields. Merged into the request body.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _deploy_app(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.deployment_json, "Deployment Spec") or {}
    if c.source_code_path is not None:
        body["source_code_path"] = c.source_code_path
    if c.mode is not None:
        body["mode"] = c.mode
    return await _databricks_request(host, token, "POST", f"/api/2.0/apps/{c.name}/deployments", json_body=body, action_name="deploy_app")


class DatabricksListAppDeploymentsConfig(BaseModel):
    """List deployments for a Databricks App."""
    operation: Literal["list_app_deployments"] = Field(
        "list_app_deployments",
        json_schema_extra={"const": "list_app_deployments", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "List App Deployments"},
        title="List App Deployments",
    )
    name: str = Field(..., title="App Name", description="The name of the app whose deployments to list.")
    page_size: Optional[str] = Field(None, title="Page Size", description="Upper bound for the number of deployments to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token to go to the next page of deployments.")


async def _list_app_deployments(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/apps/{c.name}/deployments", params={"page_size": c.page_size, "page_token": c.page_token}, action_name="list_app_deployments")


class DatabricksGetAppDeploymentConfig(BaseModel):
    """Get a specific deployment of a Databricks App."""
    operation: Literal["get_app_deployment"] = Field(
        "get_app_deployment",
        json_schema_extra={"const": "get_app_deployment", "ui:hidden": True,
                           "x-category": "Apps", "x-is-trigger": False,
                           "x-display-name": "Get App Deployment"},
        title="Get App Deployment",
    )
    name: str = Field(..., title="App Name", description="The name of the app.")
    deployment_id: str = Field(..., title="Deployment ID", description="The unique id of the deployment to retrieve.")


async def _get_app_deployment(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(host, token, "GET", f"/api/2.0/apps/{c.name}/deployments/{c.deployment_id}", action_name="get_app_deployment")


OPERATION_CONFIGS.extend([
    DatabricksListAppsConfig,
    DatabricksCreateAppConfig,
    DatabricksGetAppConfig,
    DatabricksUpdateAppConfig,
    DatabricksDeleteAppConfig,
    DatabricksStartAppConfig,
    DatabricksStopAppConfig,
    DatabricksDeployAppConfig,
    DatabricksListAppDeploymentsConfig,
    DatabricksGetAppDeploymentConfig,
])
OPERATION_HANDLERS.update({
    "list_apps": _list_apps,
    "create_app": _create_app,
    "get_app": _get_app,
    "update_app": _update_app,
    "delete_app": _delete_app,
    "start_app": _start_app,
    "stop_app": _stop_app,
    "deploy_app": _deploy_app,
    "list_app_deployments": _list_app_deployments,
    "get_app_deployment": _get_app_deployment,
})


# ---- Dashboards (13 ops) ----
class DatabricksListLakeviewDashboardsConfig(BaseModel):
    """List Lakeview (AI/BI) dashboards in the workspace."""
    operation: Literal["list_lakeview_dashboards"] = Field(
        "list_lakeview_dashboards",
        json_schema_extra={"const": "list_lakeview_dashboards", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "List Lakeview Dashboards"},
        title="List Lakeview Dashboards",
    )
    page_size: Optional[str] = Field(None, title="Page Size", description="Number of dashboards to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque token from a previous response for pagination.")
    show_trashed: str = Field(
        "false", title="Show Trashed", description="Include dashboards in the trash.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    view: Optional[str] = Field(
        None, title="View", description="Level of detail to return.",
        json_schema_extra={"enum": ["DASHBOARD_VIEW_BASIC", "DASHBOARD_VIEW_FULL"],
                           "enumNames": ["Basic", "Full"], "x-enum-searchable": True},
    )


async def _list_lakeview_dashboards(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/lakeview/dashboards",
        params={"page_size": c.page_size, "page_token": c.page_token,
                "show_trashed": c.show_trashed == "true", "view": c.view},
        action_name="list_lakeview_dashboards",
    )


class DatabricksCreateLakeviewDashboardConfig(BaseModel):
    """Create a new Lakeview (AI/BI) dashboard."""
    operation: Literal["create_lakeview_dashboard"] = Field(
        "create_lakeview_dashboard",
        json_schema_extra={"const": "create_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Create Lakeview Dashboard"},
        title="Create Lakeview Dashboard",
    )
    display_name: str = Field(..., title="Display Name", description="The display name of the dashboard.")
    warehouse_id: Optional[str] = Field(
        None, title="Warehouse", description="The SQL warehouse used to run the dashboard's queries.",
        json_schema_extra=_dyn("warehouse_id", "a warehouse"),
    )
    serialized_dashboard: Optional[str] = Field(
        None, title="Serialized Dashboard", description="The contents of the dashboard as a serialized JSON string.")
    parent_path: Optional[str] = Field(
        None, title="Parent Path", description="The workspace path of the folder containing the dashboard.")


async def _create_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", "/api/2.0/lakeview/dashboards",
        json_body={"display_name": c.display_name, "warehouse_id": c.warehouse_id,
                   "serialized_dashboard": c.serialized_dashboard, "parent_path": c.parent_path},
        action_name="create_lakeview_dashboard",
    )


class DatabricksGetLakeviewDashboardConfig(BaseModel):
    """Get a Lakeview (AI/BI) dashboard by ID."""
    operation: Literal["get_lakeview_dashboard"] = Field(
        "get_lakeview_dashboard",
        json_schema_extra={"const": "get_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Get Lakeview Dashboard"},
        title="Get Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")


async def _get_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}",
        action_name="get_lakeview_dashboard",
    )


class DatabricksUpdateLakeviewDashboardConfig(BaseModel):
    """Update a Lakeview (AI/BI) dashboard."""
    operation: Literal["update_lakeview_dashboard"] = Field(
        "update_lakeview_dashboard",
        json_schema_extra={"const": "update_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Update Lakeview Dashboard"},
        title="Update Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    display_name: Optional[str] = Field(None, title="Display Name", description="The display name of the dashboard.")
    warehouse_id: Optional[str] = Field(
        None, title="Warehouse", description="The SQL warehouse used to run the dashboard's queries.",
        json_schema_extra=_dyn("warehouse_id", "a warehouse"),
    )
    serialized_dashboard: Optional[str] = Field(
        None, title="Serialized Dashboard", description="The contents of the dashboard as a serialized JSON string.")


async def _update_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "PATCH", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}",
        json_body={"display_name": c.display_name, "warehouse_id": c.warehouse_id,
                   "serialized_dashboard": c.serialized_dashboard},
        action_name="update_lakeview_dashboard",
    )


class DatabricksTrashLakeviewDashboardConfig(BaseModel):
    """Move a Lakeview (AI/BI) dashboard to the trash."""
    operation: Literal["trash_lakeview_dashboard"] = Field(
        "trash_lakeview_dashboard",
        json_schema_extra={"const": "trash_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Trash Lakeview Dashboard"},
        title="Trash Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")


async def _trash_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}",
        action_name="trash_lakeview_dashboard",
    )


class DatabricksPublishLakeviewDashboardConfig(BaseModel):
    """Publish the current draft of a Lakeview (AI/BI) dashboard."""
    operation: Literal["publish_lakeview_dashboard"] = Field(
        "publish_lakeview_dashboard",
        json_schema_extra={"const": "publish_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Publish Lakeview Dashboard"},
        title="Publish Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    embed_credentials: str = Field(
        "false", title="Embed Credentials", description="Whether to embed the publisher's credentials in the published dashboard.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    warehouse_id: Optional[str] = Field(
        None, title="Warehouse", description="The SQL warehouse to use for the published dashboard's queries.",
        json_schema_extra=_dyn("warehouse_id", "a warehouse"),
    )


async def _publish_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/published",
        json_body={"embed_credentials": c.embed_credentials == "true", "warehouse_id": c.warehouse_id},
        action_name="publish_lakeview_dashboard",
    )


class DatabricksUnpublishLakeviewDashboardConfig(BaseModel):
    """Unpublish a Lakeview (AI/BI) dashboard."""
    operation: Literal["unpublish_lakeview_dashboard"] = Field(
        "unpublish_lakeview_dashboard",
        json_schema_extra={"const": "unpublish_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Unpublish Lakeview Dashboard"},
        title="Unpublish Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")


async def _unpublish_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/published",
        action_name="unpublish_lakeview_dashboard",
    )


class DatabricksGetPublishedLakeviewDashboardConfig(BaseModel):
    """Get the published version of a Lakeview (AI/BI) dashboard."""
    operation: Literal["get_published_lakeview_dashboard"] = Field(
        "get_published_lakeview_dashboard",
        json_schema_extra={"const": "get_published_lakeview_dashboard", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Get Published Lakeview Dashboard"},
        title="Get Published Lakeview Dashboard",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")


async def _get_published_lakeview_dashboard(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/published",
        action_name="get_published_lakeview_dashboard",
    )


class DatabricksListLakeviewSchedulesConfig(BaseModel):
    """List schedules for a Lakeview (AI/BI) dashboard."""
    operation: Literal["list_lakeview_schedules"] = Field(
        "list_lakeview_schedules",
        json_schema_extra={"const": "list_lakeview_schedules", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "List Lakeview Schedules"},
        title="List Lakeview Schedules",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    page_size: Optional[str] = Field(None, title="Page Size", description="Number of schedules to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Opaque token from a previous response for pagination.")


async def _list_lakeview_schedules(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/schedules",
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_lakeview_schedules",
    )


class DatabricksCreateLakeviewScheduleConfig(BaseModel):
    """Create a schedule for a Lakeview (AI/BI) dashboard."""
    operation: Literal["create_lakeview_schedule"] = Field(
        "create_lakeview_schedule",
        json_schema_extra={"const": "create_lakeview_schedule", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Create Lakeview Schedule"},
        title="Create Lakeview Schedule",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    schedule_json: str = Field(
        "{}", title="Schedule (JSON)",
        description='The schedule spec, e.g. {"cron_schedule": {"quartz_cron_expression": "0 0 8 * * ?", "timezone_id": "UTC"}, "display_name": "Daily", "pause_status": "UNPAUSED"}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _create_lakeview_schedule(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.schedule_json, "Schedule") or {}
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/schedules",
        json_body=body, action_name="create_lakeview_schedule",
    )


class DatabricksGetLakeviewScheduleConfig(BaseModel):
    """Get a schedule for a Lakeview (AI/BI) dashboard."""
    operation: Literal["get_lakeview_schedule"] = Field(
        "get_lakeview_schedule",
        json_schema_extra={"const": "get_lakeview_schedule", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Get Lakeview Schedule"},
        title="Get Lakeview Schedule",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    schedule_id: str = Field(..., title="Schedule ID", description="The UUID identifying the schedule.")


async def _get_lakeview_schedule(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/schedules/{c.schedule_id}",
        action_name="get_lakeview_schedule",
    )


class DatabricksUpdateLakeviewScheduleConfig(BaseModel):
    """Update a schedule for a Lakeview (AI/BI) dashboard."""
    operation: Literal["update_lakeview_schedule"] = Field(
        "update_lakeview_schedule",
        json_schema_extra={"const": "update_lakeview_schedule", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Update Lakeview Schedule"},
        title="Update Lakeview Schedule",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    schedule_id: str = Field(..., title="Schedule ID", description="The UUID identifying the schedule.")
    schedule_json: str = Field(
        "{}", title="Schedule (JSON)",
        description='The updated schedule spec, e.g. {"cron_schedule": {"quartz_cron_expression": "0 0 8 * * ?", "timezone_id": "UTC"}, "display_name": "Daily", "pause_status": "UNPAUSED", "etag": "..."}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


async def _update_lakeview_schedule(c, host, token) -> Dict[str, Any]:
    body = _parse_json_field(c.schedule_json, "Schedule") or {}
    return await _databricks_request(
        host, token, "PUT", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/schedules/{c.schedule_id}",
        json_body=body, action_name="update_lakeview_schedule",
    )


class DatabricksDeleteLakeviewScheduleConfig(BaseModel):
    """Delete a schedule for a Lakeview (AI/BI) dashboard."""
    operation: Literal["delete_lakeview_schedule"] = Field(
        "delete_lakeview_schedule",
        json_schema_extra={"const": "delete_lakeview_schedule", "ui:hidden": True,
                           "x-category": "Dashboards", "x-is-trigger": False,
                           "x-display-name": "Delete Lakeview Schedule"},
        title="Delete Lakeview Schedule",
    )
    dashboard_id: str = Field(..., title="Dashboard ID", description="The UUID identifying the dashboard.")
    schedule_id: str = Field(..., title="Schedule ID", description="The UUID identifying the schedule.")


async def _delete_lakeview_schedule(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "DELETE", f"/api/2.0/lakeview/dashboards/{c.dashboard_id}/schedules/{c.schedule_id}",
        action_name="delete_lakeview_schedule",
    )


OPERATION_CONFIGS.extend([
    DatabricksListLakeviewDashboardsConfig,
    DatabricksCreateLakeviewDashboardConfig,
    DatabricksGetLakeviewDashboardConfig,
    DatabricksUpdateLakeviewDashboardConfig,
    DatabricksTrashLakeviewDashboardConfig,
    DatabricksPublishLakeviewDashboardConfig,
    DatabricksUnpublishLakeviewDashboardConfig,
    DatabricksGetPublishedLakeviewDashboardConfig,
    DatabricksListLakeviewSchedulesConfig,
    DatabricksCreateLakeviewScheduleConfig,
    DatabricksGetLakeviewScheduleConfig,
    DatabricksUpdateLakeviewScheduleConfig,
    DatabricksDeleteLakeviewScheduleConfig,
])
OPERATION_HANDLERS.update({
    "list_lakeview_dashboards": _list_lakeview_dashboards,
    "create_lakeview_dashboard": _create_lakeview_dashboard,
    "get_lakeview_dashboard": _get_lakeview_dashboard,
    "update_lakeview_dashboard": _update_lakeview_dashboard,
    "trash_lakeview_dashboard": _trash_lakeview_dashboard,
    "publish_lakeview_dashboard": _publish_lakeview_dashboard,
    "unpublish_lakeview_dashboard": _unpublish_lakeview_dashboard,
    "get_published_lakeview_dashboard": _get_published_lakeview_dashboard,
    "list_lakeview_schedules": _list_lakeview_schedules,
    "create_lakeview_schedule": _create_lakeview_schedule,
    "get_lakeview_schedule": _get_lakeview_schedule,
    "update_lakeview_schedule": _update_lakeview_schedule,
    "delete_lakeview_schedule": _delete_lakeview_schedule,
})


# ---- Genie (9 ops) ----
class DatabricksListGenieSpacesConfig(BaseModel):
    """List Genie spaces the caller can access."""
    operation: Literal["list_genie_spaces"] = Field(
        "list_genie_spaces",
        json_schema_extra={"const": "list_genie_spaces", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "List Genie Spaces"},
        title="List Genie Spaces",
    )
    page_size: Optional[str] = Field(None, title="Page Size", description="Maximum number of spaces to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token from a previous response.")


class DatabricksGetGenieSpaceConfig(BaseModel):
    """Get metadata for a single Genie space."""
    operation: Literal["get_genie_space"] = Field(
        "get_genie_space",
        json_schema_extra={"const": "get_genie_space", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Get Genie Space"},
        title="Get Genie Space",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")


class DatabricksStartGenieConversationConfig(BaseModel):
    """Start a new Genie conversation with an initial message."""
    operation: Literal["start_genie_conversation"] = Field(
        "start_genie_conversation",
        json_schema_extra={"const": "start_genie_conversation", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Start Genie Conversation"},
        title="Start Genie Conversation",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    content: str = Field(..., title="Message Content", description="The natural-language question that starts the conversation.")


class DatabricksCreateGenieMessageConfig(BaseModel):
    """Add a follow-up message to an existing Genie conversation."""
    operation: Literal["create_genie_message"] = Field(
        "create_genie_message",
        json_schema_extra={"const": "create_genie_message", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Create Genie Message"},
        title="Create Genie Message",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to append the message to.")
    content: str = Field(..., title="Message Content", description="The natural-language follow-up question.")


class DatabricksGetGenieMessageConfig(BaseModel):
    """Get a message (and its status/attachments) from a Genie conversation."""
    operation: Literal["get_genie_message"] = Field(
        "get_genie_message",
        json_schema_extra={"const": "get_genie_message", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Get Genie Message"},
        title="Get Genie Message",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation identifier.")
    message_id: str = Field(..., title="Message ID", description="The message identifier.")


class DatabricksGetGenieMessageQueryResultConfig(BaseModel):
    """Get the SQL query result for a Genie message."""
    operation: Literal["get_genie_message_query_result"] = Field(
        "get_genie_message_query_result",
        json_schema_extra={"const": "get_genie_message_query_result", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Get Genie Message Query Result"},
        title="Get Genie Message Query Result",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation identifier.")
    message_id: str = Field(..., title="Message ID", description="The message identifier.")


class DatabricksExecuteGenieMessageQueryConfig(BaseModel):
    """Execute the SQL query generated for a Genie message."""
    operation: Literal["execute_genie_message_query"] = Field(
        "execute_genie_message_query",
        json_schema_extra={"const": "execute_genie_message_query", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Execute Genie Message Query"},
        title="Execute Genie Message Query",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation identifier.")
    message_id: str = Field(..., title="Message ID", description="The message identifier.")


class DatabricksGetGenieMessageAttachmentQueryResultConfig(BaseModel):
    """Get the query result for a specific attachment on a Genie message."""
    operation: Literal["get_genie_message_attachment_query_result"] = Field(
        "get_genie_message_attachment_query_result",
        json_schema_extra={"const": "get_genie_message_attachment_query_result", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "Get Genie Message Attachment Query Result"},
        title="Get Genie Message Attachment Query Result",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation identifier.")
    message_id: str = Field(..., title="Message ID", description="The message identifier.")
    attachment_id: str = Field(..., title="Attachment ID", description="The attachment identifier on the message.")


class DatabricksListGenieConversationsConfig(BaseModel):
    """List conversations in a Genie space."""
    operation: Literal["list_genie_conversations"] = Field(
        "list_genie_conversations",
        json_schema_extra={"const": "list_genie_conversations", "ui:hidden": True,
                           "x-category": "Genie", "x-is-trigger": False,
                           "x-display-name": "List Genie Conversations"},
        title="List Genie Conversations",
    )
    space_id: str = Field(..., title="Space ID", description="The Genie space identifier.")
    page_size: Optional[str] = Field(None, title="Page Size", description="Maximum number of conversations to return per page.")
    page_token: Optional[str] = Field(None, title="Page Token", description="Pagination token from a previous response.")


async def _list_genie_spaces(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", "/api/2.0/genie/spaces",
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_genie_spaces",
    )


async def _get_genie_space(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET", f"/api/2.0/genie/spaces/{c.space_id}",
        action_name="get_genie_space",
    )


async def _start_genie_conversation(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST", f"/api/2.0/genie/spaces/{c.space_id}/start-conversation",
        json_body={"content": c.content},
        action_name="start_genie_conversation",
    )


async def _create_genie_message(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations/{c.conversation_id}/messages",
        json_body={"content": c.content},
        action_name="create_genie_message",
    )


async def _get_genie_message(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations/{c.conversation_id}/messages/{c.message_id}",
        action_name="get_genie_message",
    )


async def _get_genie_message_query_result(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations/{c.conversation_id}/messages/{c.message_id}/query-result",
        action_name="get_genie_message_query_result",
    )


async def _execute_genie_message_query(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "POST",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations/{c.conversation_id}/messages/{c.message_id}/execute-query",
        action_name="execute_genie_message_query",
    )


async def _get_genie_message_attachment_query_result(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations/{c.conversation_id}/messages/{c.message_id}/attachments/{c.attachment_id}/query-result",
        action_name="get_genie_message_attachment_query_result",
    )


async def _list_genie_conversations(c, host, token) -> Dict[str, Any]:
    return await _databricks_request(
        host, token, "GET",
        f"/api/2.0/genie/spaces/{c.space_id}/conversations",
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_genie_conversations",
    )


OPERATION_CONFIGS.extend([
    DatabricksListGenieSpacesConfig,
    DatabricksGetGenieSpaceConfig,
    DatabricksStartGenieConversationConfig,
    DatabricksCreateGenieMessageConfig,
    DatabricksGetGenieMessageConfig,
    DatabricksGetGenieMessageQueryResultConfig,
    DatabricksExecuteGenieMessageQueryConfig,
    DatabricksGetGenieMessageAttachmentQueryResultConfig,
    DatabricksListGenieConversationsConfig,
])
OPERATION_HANDLERS.update({
    "list_genie_spaces": _list_genie_spaces,
    "get_genie_space": _get_genie_space,
    "start_genie_conversation": _start_genie_conversation,
    "create_genie_message": _create_genie_message,
    "get_genie_message": _get_genie_message,
    "get_genie_message_query_result": _get_genie_message_query_result,
    "execute_genie_message_query": _execute_genie_message_query,
    "get_genie_message_attachment_query_result": _get_genie_message_attachment_query_result,
    "list_genie_conversations": _list_genie_conversations,
})


# ============================================================================
# Discriminated Union
# ============================================================================


DatabricksConfig = Annotated[
    Union[
        DatabricksRunStatementConfig,
        DatabricksGetStatementConfig,
        DatabricksCancelStatementConfig,
        DatabricksListWarehousesConfig,
        DatabricksGetWarehouseConfig,
        DatabricksStartWarehouseConfig,
        DatabricksStopWarehouseConfig,
        DatabricksListJobsConfig,
        DatabricksGetJobConfig,
        DatabricksCreateJobConfig,
        DatabricksRunNowConfig,
        DatabricksSubmitRunConfig,
        DatabricksListRunsConfig,
        DatabricksGetRunConfig,
        DatabricksGetRunOutputConfig,
        DatabricksCancelRunConfig,
        DatabricksDeleteJobConfig,
        DatabricksListClustersConfig,
        DatabricksGetClusterConfig,
        DatabricksCreateClusterConfig,
        DatabricksStartClusterConfig,
        DatabricksTerminateClusterConfig,
        DatabricksListCatalogsConfig,
        DatabricksListSchemasConfig,
        DatabricksListTablesConfig,
        DatabricksGetTableConfig,
        DatabricksListWorkspaceConfig,
        DatabricksExportWorkspaceConfig,
        DatabricksImportWorkspaceConfig,
        DatabricksListSecretScopesConfig,
        *DATABRICKS_TRIGGER_CONFIGS.values(),
        *OPERATION_CONFIGS,
    ],
    Discriminator("operation"),
]


class DatabricksNodeConfig(NodeConfig[DatabricksConfig, DatabricksCredential]):
    """Full configuration for the Databricks node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _parse_json_field(value: Optional[str], field_label: str) -> Any:
    """Parse a JSON string config field, raising a clear error on failure."""
    if value is None or value == "":
        return None
    import json

    try:
        return json.loads(value)
    except Exception as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")


async def _databricks_request(
    host: str,
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    content_type: str = "application/json",
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    """Make an authenticated Databricks REST request and return a structured result.

    ``content_type`` overrides the request Content-Type (SCIM needs
    ``application/scim+json``). ``data`` sends a raw request body (bytes/str)
    instead of JSON — used by the Files API; when set, ``json_body`` is ignored.
    """
    url = f"{host}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": content_type,
    }
    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=60.0) as client:
        try:
            if data is not None:
                response = await client.request(
                    method=method, url=url, headers=headers, params=params, content=data
                )
            else:
                response = await client.request(
                    method=method, url=url, headers=headers, params=params, json=json_body
                )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("message")
                        or err.get("error_code")
                        or err.get("error")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DatabricksNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.text:
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
            logger.error(f"[DatabricksNode] Request failed ({action_name}): {msg}")
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


class DatabricksNode(WorkflowNode):
    """Databricks workspace automation node."""

    edit_examples = [
        "Run a SQL query on a SQL warehouse and return the results",
        "Trigger a job run now and poll for its status",
        "List the tables in a Unity Catalog schema",
        "Start a SQL warehouse before running queries",
        "Trigger a workflow when a Databricks job sends a webhook notification",
    ]

    @classmethod
    def get_config_model(cls):
        return DatabricksNodeConfig

    # ------------------------------------------------------------------
    # Webhook event filtering (no per-subscription filter at the provider)
    # ------------------------------------------------------------------
    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip webhook deliveries whose event_type isn't this trigger's event.

        Databricks posts every configured job notification (start / success /
        failure / duration-warning) to the same destination URL with the kind
        in the payload's ``event_type`` field, so each per-event trigger filters
        here. The ``on_any_job_event`` trigger (event ``*``) — and any unknown
        operation — passes everything so a misconfigured filter never silently
        drops every event.
        """
        event = DATABRICKS_TRIGGER_EVENT.get((config or {}).get("operation"), "*")
        if event == "*":
            return True
        return payload.get("event_type") == event

    # ------------------------------------------------------------------
    # Webhook receiver URL provisioning (dashboard-configured destination)
    # ------------------------------------------------------------------
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
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    # ------------------------------------------------------------------
    # Dynamic options (warehouses, jobs, clusters, catalogs)
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
        if not credential_data:
            return {"options": []}
        host = _normalize_host(credential_data.get("workspace_url", ""))
        token = credential_data.get("access_token")
        if not token:
            return {"options": []}

        if field_name == "warehouse_id":
            result = await _databricks_request(
                host, token, "GET", "/api/2.0/sql/warehouses", action_name="list_warehouses"
            )
            warehouses = (result.get("data") or {}).get("warehouses", []) if result.get("status") == "success" else []
            return {
                "options": [
                    {"label": w.get("name") or w.get("id"), "value": str(w.get("id"))}
                    for w in warehouses
                    if isinstance(w, dict) and w.get("id")
                ]
            }
        if field_name == "job_id":
            result = await _databricks_request(
                host, token, "GET", "/api/2.2/jobs/list", params={"limit": 100}, action_name="list_jobs"
            )
            jobs = (result.get("data") or {}).get("jobs", []) if result.get("status") == "success" else []
            options = []
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                jid = j.get("job_id")
                name = (j.get("settings") or {}).get("name") or f"Job {jid}"
                if jid is not None:
                    options.append({"label": name, "value": str(jid)})
            return {"options": options}
        if field_name == "cluster_id":
            result = await _databricks_request(
                host, token, "GET", "/api/2.1/clusters/list", action_name="list_clusters"
            )
            clusters = (result.get("data") or {}).get("clusters", []) if result.get("status") == "success" else []
            return {
                "options": [
                    {
                        "label": c.get("cluster_name") or c.get("cluster_id"),
                        "value": str(c.get("cluster_id")),
                    }
                    for c in clusters
                    if isinstance(c, dict) and c.get("cluster_id")
                ]
            }
        if field_name == "catalog_name":
            result = await _databricks_request(
                host, token, "GET", "/api/2.1/unity-catalog/catalogs", action_name="list_catalogs"
            )
            catalogs = (result.get("data") or {}).get("catalogs", []) if result.get("status") == "success" else []
            return {
                "options": [
                    {"label": c.get("name"), "value": str(c.get("name"))}
                    for c in catalogs
                    if isinstance(c, dict) and c.get("name")
                ]
            }
        return {"options": []}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, DatabricksNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _DatabricksWebhookTrigger):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Databricks workspace URL and access token.")
        host = _normalize_host(credentials.workspace_url)
        token = credentials.access_token

        handlers = {
            "run_statement": self._run_statement,
            "get_statement": self._get_statement,
            "cancel_statement": self._cancel_statement,
            "list_warehouses": self._list_warehouses,
            "get_warehouse": self._get_warehouse,
            "start_warehouse": self._start_warehouse,
            "stop_warehouse": self._stop_warehouse,
            "list_jobs": self._list_jobs,
            "get_job": self._get_job,
            "create_job": self._create_job,
            "run_now": self._run_now,
            "submit_run": self._submit_run,
            "list_runs": self._list_runs,
            "get_run": self._get_run,
            "get_run_output": self._get_run_output,
            "cancel_run": self._cancel_run,
            "delete_job": self._delete_job,
            "list_clusters": self._list_clusters,
            "get_cluster": self._get_cluster,
            "create_cluster": self._create_cluster,
            "start_cluster": self._start_cluster,
            "terminate_cluster": self._terminate_cluster,
            "list_catalogs": self._list_catalogs,
            "list_schemas": self._list_schemas,
            "list_tables": self._list_tables,
            "get_table": self._get_table,
            "list_workspace": self._list_workspace,
            "export_workspace": self._export_workspace,
            "import_workspace": self._import_workspace,
            "list_secret_scopes": self._list_secret_scopes,
        }
        # Registry ops from the generated per-service blocks. Module-level
        # handlers take the same (c, host, token) args as the curated ones.
        handlers.update(OPERATION_HANDLERS)
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, host, token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # SQL handlers
    # ------------------------------------------------------------------
    async def _run_statement(self, c: DatabricksRunStatementConfig, host: str, token: str) -> Dict[str, Any]:
        body = {
            "warehouse_id": c.warehouse_id,
            "statement": c.statement,
            "catalog": c.catalog,
            "schema": c.db_schema,
            "wait_timeout": c.wait_timeout,
            "on_wait_timeout": c.on_wait_timeout,
        }
        return await _databricks_request(
            host, token, "POST", "/api/2.0/sql/statements", json_body=body, action_name="run_statement"
        )

    async def _get_statement(self, c: DatabricksGetStatementConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", f"/api/2.0/sql/statements/{c.statement_id}", action_name="get_statement"
        )

    async def _cancel_statement(self, c: DatabricksCancelStatementConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "POST", f"/api/2.0/sql/statements/{c.statement_id}/cancel", action_name="cancel_statement"
        )

    # ------------------------------------------------------------------
    # Warehouse handlers
    # ------------------------------------------------------------------
    async def _list_warehouses(self, c: DatabricksListWarehousesConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.0/sql/warehouses", action_name="list_warehouses"
        )

    async def _get_warehouse(self, c: DatabricksGetWarehouseConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", f"/api/2.0/sql/warehouses/{c.warehouse_id}", action_name="get_warehouse"
        )

    async def _start_warehouse(self, c: DatabricksStartWarehouseConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "POST", f"/api/2.0/sql/warehouses/{c.warehouse_id}/start", action_name="start_warehouse"
        )

    async def _stop_warehouse(self, c: DatabricksStopWarehouseConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "POST", f"/api/2.0/sql/warehouses/{c.warehouse_id}/stop", action_name="stop_warehouse"
        )

    # ------------------------------------------------------------------
    # Job handlers
    # ------------------------------------------------------------------
    async def _list_jobs(self, c: DatabricksListJobsConfig, host: str, token: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "page_token": c.page_token}
        return await _databricks_request(
            host, token, "GET", "/api/2.2/jobs/list", params=params, action_name="list_jobs"
        )

    async def _get_job(self, c: DatabricksGetJobConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.2/jobs/get", params={"job_id": c.job_id}, action_name="get_job"
        )

    async def _create_job(self, c: DatabricksCreateJobConfig, host: str, token: str) -> Dict[str, Any]:
        body = {"name": c.name, "tasks": _parse_json_field(c.tasks_json, "Tasks")}
        return await _databricks_request(
            host, token, "POST", "/api/2.2/jobs/create", json_body=body, action_name="create_job"
        )

    async def _run_now(self, c: DatabricksRunNowConfig, host: str, token: str) -> Dict[str, Any]:
        body = {
            "job_id": int(c.job_id) if str(c.job_id).isdigit() else c.job_id,
            "job_parameters": _parse_json_field(c.job_parameters_json, "Job Parameters"),
        }
        return await _databricks_request(
            host, token, "POST", "/api/2.2/jobs/run-now", json_body=body, action_name="run_now"
        )

    async def _submit_run(self, c: DatabricksSubmitRunConfig, host: str, token: str) -> Dict[str, Any]:
        body = {"run_name": c.run_name, "tasks": _parse_json_field(c.tasks_json, "Tasks")}
        return await _databricks_request(
            host, token, "POST", "/api/2.2/jobs/runs/submit", json_body=body, action_name="submit_run"
        )

    async def _list_runs(self, c: DatabricksListRunsConfig, host: str, token: str) -> Dict[str, Any]:
        params = {
            "job_id": c.job_id,
            "active_only": c.active_only,
            "limit": c.limit,
        }
        return await _databricks_request(
            host, token, "GET", "/api/2.2/jobs/runs/list", params=params, action_name="list_runs"
        )

    async def _get_run(self, c: DatabricksGetRunConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.2/jobs/runs/get", params={"run_id": c.run_id}, action_name="get_run"
        )

    async def _get_run_output(self, c: DatabricksGetRunOutputConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.2/jobs/runs/get-output", params={"run_id": c.run_id}, action_name="get_run_output"
        )

    async def _cancel_run(self, c: DatabricksCancelRunConfig, host: str, token: str) -> Dict[str, Any]:
        body = {"run_id": int(c.run_id) if str(c.run_id).isdigit() else c.run_id}
        return await _databricks_request(
            host, token, "POST", "/api/2.2/jobs/runs/cancel", json_body=body, action_name="cancel_run"
        )

    async def _delete_job(self, c: DatabricksDeleteJobConfig, host: str, token: str) -> Dict[str, Any]:
        body = {"job_id": int(c.job_id) if str(c.job_id).isdigit() else c.job_id}
        return await _databricks_request(
            host, token, "POST", "/api/2.2/jobs/delete", json_body=body, action_name="delete_job"
        )

    # ------------------------------------------------------------------
    # Cluster handlers
    # ------------------------------------------------------------------
    async def _list_clusters(self, c: DatabricksListClustersConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.1/clusters/list", params={"page_token": c.page_token}, action_name="list_clusters"
        )

    async def _get_cluster(self, c: DatabricksGetClusterConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.1/clusters/get", params={"cluster_id": c.cluster_id}, action_name="get_cluster"
        )

    async def _create_cluster(self, c: DatabricksCreateClusterConfig, host: str, token: str) -> Dict[str, Any]:
        body = {
            "cluster_name": c.cluster_name,
            "spark_version": c.spark_version,
            "node_type_id": c.node_type_id,
            "num_workers": int(c.num_workers) if c.num_workers and str(c.num_workers).isdigit() else c.num_workers,
        }
        return await _databricks_request(
            host, token, "POST", "/api/2.1/clusters/create", json_body=body, action_name="create_cluster"
        )

    async def _start_cluster(self, c: DatabricksStartClusterConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "POST", "/api/2.1/clusters/start", json_body={"cluster_id": c.cluster_id}, action_name="start_cluster"
        )

    async def _terminate_cluster(self, c: DatabricksTerminateClusterConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "POST", "/api/2.1/clusters/delete", json_body={"cluster_id": c.cluster_id}, action_name="terminate_cluster"
        )

    # ------------------------------------------------------------------
    # Unity Catalog handlers
    # ------------------------------------------------------------------
    async def _list_catalogs(self, c: DatabricksListCatalogsConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.1/unity-catalog/catalogs", action_name="list_catalogs"
        )

    async def _list_schemas(self, c: DatabricksListSchemasConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.1/unity-catalog/schemas",
            params={"catalog_name": c.catalog_name}, action_name="list_schemas"
        )

    async def _list_tables(self, c: DatabricksListTablesConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.1/unity-catalog/tables",
            params={"catalog_name": c.catalog_name, "schema_name": c.schema_name}, action_name="list_tables"
        )

    async def _get_table(self, c: DatabricksGetTableConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", f"/api/2.1/unity-catalog/tables/{c.full_name}", action_name="get_table"
        )

    # ------------------------------------------------------------------
    # Workspace handlers
    # ------------------------------------------------------------------
    async def _list_workspace(self, c: DatabricksListWorkspaceConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.0/workspace/list", params={"path": c.path}, action_name="list_workspace"
        )

    async def _export_workspace(self, c: DatabricksExportWorkspaceConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.0/workspace/export",
            params={"path": c.path, "format": c.export_format}, action_name="export_workspace"
        )

    async def _import_workspace(self, c: DatabricksImportWorkspaceConfig, host: str, token: str) -> Dict[str, Any]:
        body = {
            "path": c.path,
            "content": c.content,
            "format": c.import_format,
            "language": c.language if c.import_format == "SOURCE" else None,
            "overwrite": c.overwrite == "true",
        }
        return await _databricks_request(
            host, token, "POST", "/api/2.0/workspace/import", json_body=body, action_name="import_workspace"
        )

    # ------------------------------------------------------------------
    # Secrets handlers
    # ------------------------------------------------------------------
    async def _list_secret_scopes(self, c: DatabricksListSecretScopesConfig, host: str, token: str) -> Dict[str, Any]:
        return await _databricks_request(
            host, token, "GET", "/api/2.0/secrets/scopes/list", action_name="list_secret_scopes"
        )
