"""
Snowflake data-cloud automation node.

Provides workflow integration with the Snowflake REST API v2 for operations
including:
- SQL: run statement, get statement status/results, cancel statement
- Databases: list, create, fetch, delete
- Schemas / Tables: list schemas, list tables, fetch table
- Warehouses: list, create, resume, suspend, abort queries
- Tasks: list, create, execute, resume, suspend, list run history
- Users / Roles: list users, create user, delete user, list roles
- Stages: list stages

Authentication: Bearer token against the customer's own account host. The
self-serve path is a Programmatic Access Token (PAT) minted in Snowsight; the
account identifier is collected as a connection field because Snowflake has no
global API host (every request targets `<account>.snowflakecomputing.com`).

API Base URL: https://<account_identifier>.snowflakecomputing.com/api/v2
Documentation: https://docs.snowflake.com/en/developer-guide/snowflake-rest-api/snowflake-rest-api
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import ScheduledPollTriggerMixin, PollTriggerConfigBase
from utils.ssrf import normalize_provider_subdomain

logger = logging.getLogger(__name__)


def _account_host(account_identifier: str) -> str:
    """Build the per-tenant Snowflake host from the account identifier.

    Accepts a bare identifier (`orgname-account_name`) or a full host/URL and
    normalizes to `https://<account>.snowflakecomputing.com`.
    """
    ident = normalize_provider_subdomain(
        account_identifier,
        "snowflakecomputing.com",
        field_name="Snowflake account identifier",
        allow_nested_labels=True,
    )
    return f"https://{ident}.snowflakecomputing.com"


def _sf_bool(v):
    """Optional string-enum ('true'/'false') -> bool, or None if unset. Shared by
    the generated control-plane handlers so bodies/params omit unset booleans."""
    return None if v in (None, "") else str(v).lower() == "true"


def _sf_int(v):
    """Optional string -> int, or None if unset / non-numeric. Shared by the
    generated control-plane handlers."""
    return int(v) if v not in (None, "") and str(v).lstrip("-").isdigit() else None


def _sf_json(v):
    """Optional JSON-string field -> parsed value, or None if unset. Raises a
    clean ValueError on malformed JSON so a bad input surfaces as a node error
    instead of an unhandled exception. Shared by generated handlers whose bodies
    take structured (array/object) fields as a JSON string."""
    if v in (None, ""):
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"Invalid JSON in field: {e}")


_SF_LAG_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
    "day": 86400, "days": 86400,
}


def _sf_target_lag(v):
    """Dynamic-table TargetLag object from a user string. The REST API needs a
    structured object, not a raw string: 'DOWNSTREAM' -> {"type":"DOWNSTREAM"};
    a duration ('1 hour', '60 seconds', '5 minutes', '2 days') or a bare number
    of seconds -> {"type":"USER_DEFINED","seconds":N}."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    if s.upper() == "DOWNSTREAM":
        return {"type": "DOWNSTREAM"}
    parts = s.split()
    if len(parts) == 2 and parts[0].isdigit() and parts[1].lower() in _SF_LAG_UNITS:
        seconds = int(parts[0]) * _SF_LAG_UNITS[parts[1].lower()]
    elif s.isdigit():
        seconds = int(s)
    else:
        raise ValueError(
            f"Invalid target_lag '{v}'. Use e.g. '1 hour', '60 seconds', '2 days', "
            "'DOWNSTREAM', or a number of seconds."
        )
    return {"type": "USER_DEFINED", "seconds": seconds}


def _sf_task_schedule(v):
    """Task schedule string -> TaskSchedule object (the REST API needs an object,
    not a raw string). '<N> MINUTE'/'<N> minutes'/a bare number -> MINUTES_TYPE;
    'USING CRON <cron_expr> <timezone>' -> CRON_TYPE."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    if s.upper().startswith("USING CRON"):
        toks = s[len("USING CRON"):].strip().split()
        if len(toks) < 2:
            raise ValueError(
                f"Invalid CRON task schedule '{v}'. Use 'USING CRON <expr> <timezone>'."
            )
        return {"schedule_type": "CRON_TYPE", "cron_expr": " ".join(toks[:-1]), "timezone": toks[-1]}
    parts = s.split()
    if parts and parts[0].isdigit():
        return {"schedule_type": "MINUTES_TYPE", "minutes": int(parts[0])}
    raise ValueError(
        f"Invalid task schedule '{v}'. Use e.g. '5 MINUTE' or 'USING CRON 0 9 * * * UTC'."
    )


# ============================================================================
# Credential Schema
# ============================================================================


class SnowflakePatCredential(BaseModel):
    """Programmatic Access Token credential for Snowflake.

    A PAT is minted per-user in Snowsight (Account/Profile > Programmatic access
    tokens). It is passed as a Bearer token with the
    `X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN` header.
    The account identifier is required because the host is per-tenant.
    """

    credential_type: Literal["snowflake_pat"] = Field(
        "snowflake_pat", json_schema_extra={"ui:hidden": True}
    )
    account_identifier: str = Field(
        ...,
        title="Account Identifier",
        description=(
            "Your Snowflake account, e.g. 'myorg-myaccount' (or the full "
            "<account>.snowflakecomputing.com host). Found in Snowsight under "
            "Account details."
        ),
    )
    token: str = Field(
        ...,
        title="Programmatic Access Token",
        description=(
            "A Programmatic Access Token minted in Snowsight under "
            "Account/Profile > Programmatic access tokens."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://docs.snowflake.com/en/user-guide/programmatic-access-tokens"
        }
    )


# Snowflake auth is PAT-only. OAuth is intentionally NOT supported: Snowflake
# OAuth is per-tenant + bring-your-own-app (the client must be registered inside
# each customer's own account via CREATE SECURITY INTEGRATION), so there is no
# NoClick-owned global app and no zero-setup flow — the PAT covers every
# operation with far less friction.
SnowflakeCredential = SnowflakePatCredential


# ============================================================================
# SQL Operation Configs
# ============================================================================


class SnowflakeRunStatementConfig(BaseModel):
    """Execute a SQL statement (query / DML / DDL) via the SQL API."""

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
    statement: str = Field(
        ...,
        title="SQL Statement",
        description="The SQL to execute, e.g. SELECT * FROM my_table LIMIT 10",
        json_schema_extra={"ui:widget": "textarea"},
    )
    warehouse: Optional[str] = Field(
        None,
        title="Warehouse",
        description="Compute warehouse to run the statement on",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "warehouse",
                "placeholder": "Select a warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a warehouse name",
            }
        },
    )
    database: Optional[str] = Field(
        None,
        title="Database",
        description="Database context for the statement",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )
    schema_name: Optional[str] = Field(
        None, title="Schema", description="Schema context for the statement"
    )
    role: Optional[str] = Field(
        None,
        title="Role",
        description="Role to run the statement as",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "role",
                "placeholder": "Select a role...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a role name",
            }
        },
    )
    timeout: Optional[str] = Field(
        None,
        title="Timeout (seconds)",
        description="Server-side execution timeout in seconds",
    )
    run_async: Optional[str] = Field(
        "false",
        title="Run Asynchronously",
        description="Submit asynchronously and return a statement handle to poll",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class SnowflakeGetStatementConfig(BaseModel):
    """Check status / fetch result rows for a previously submitted statement."""

    operation: Literal["get_statement"] = Field(
        "get_statement",
        json_schema_extra={
            "const": "get_statement",
            "ui:hidden": True,
            "x-category": "SQL",
            "x-is-trigger": False,
            "x-display-name": "Get Statement Status / Results",
        },
        title="Get Statement Status / Results",
    )
    statement_handle: str = Field(
        ...,
        title="Statement Handle",
        description="The statementHandle returned by a (usually async) run",
    )
    partition: Optional[str] = Field(
        None,
        title="Partition",
        description="Result partition index to fetch (0-based)",
    )


class SnowflakeCancelStatementConfig(BaseModel):
    """Abort an in-flight async statement."""

    operation: Literal["cancel_statement"] = Field(
        "cancel_statement",
        json_schema_extra={
            "const": "cancel_statement",
            "ui:hidden": True,
            "x-category": "SQL",
            "x-is-trigger": False,
            "x-display-name": "Cancel Statement",
        },
        title="Cancel Statement",
    )
    statement_handle: str = Field(
        ..., title="Statement Handle", description="The statementHandle to abort"
    )


# ============================================================================
# Database Operation Configs
# ============================================================================


class SnowflakeListDatabasesConfig(BaseModel):
    """List accessible databases."""

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
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )
    starts_with: Optional[str] = Field(
        None, title="Starts With", description="Case-sensitive name prefix filter"
    )
    show_limit: Optional[str] = Field(
        None, title="Limit", description="Maximum number of rows to return"
    )


class SnowflakeCreateDatabaseConfig(BaseModel):
    """Create a new database."""

    operation: Literal["create_database"] = Field(
        "create_database",
        json_schema_extra={
            "const": "create_database",
            "x-creates-resource": True,
            "x-resource-type": "snowflake_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Create Database",
        },
        title="Create Database",
    )
    name: str = Field(..., title="Name", description="Name of the database to create")
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional description for the database"
    )


class SnowflakeFetchDatabaseConfig(BaseModel):
    """Describe a single database."""

    operation: Literal["fetch_database"] = Field(
        "fetch_database",
        json_schema_extra={
            "const": "fetch_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Fetch Database",
        },
        title="Fetch Database",
    )
    name: str = Field(
        ...,
        title="Database",
        description="The database to describe",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )


class SnowflakeDeleteDatabaseConfig(BaseModel):
    """Drop a named database."""

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
    name: str = Field(
        ...,
        title="Database",
        description="The database to drop",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )


# ============================================================================
# Schema / Table Operation Configs
# ============================================================================


class SnowflakeListSchemasConfig(BaseModel):
    """List schemas within a database."""

    operation: Literal["list_schemas"] = Field(
        "list_schemas",
        json_schema_extra={
            "const": "list_schemas",
            "ui:hidden": True,
            "x-category": "Schemas & Tables",
            "x-is-trigger": False,
            "x-display-name": "List Schemas",
        },
        title="List Schemas",
    )
    database: str = Field(
        ...,
        title="Database",
        description="The database whose schemas to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


class SnowflakeListTablesConfig(BaseModel):
    """List tables in a schema."""

    operation: Literal["list_tables"] = Field(
        "list_tables",
        json_schema_extra={
            "const": "list_tables",
            "ui:hidden": True,
            "x-category": "Schemas & Tables",
            "x-is-trigger": False,
            "x-display-name": "List Tables",
        },
        title="List Tables",
    )
    database: str = Field(
        ...,
        title="Database",
        description="The database containing the schema",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )
    schema_name: str = Field(
        ..., title="Schema", description="The schema whose tables to list"
    )
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


class SnowflakeFetchTableConfig(BaseModel):
    """Describe a single table's metadata / columns."""

    operation: Literal["fetch_table"] = Field(
        "fetch_table",
        json_schema_extra={
            "const": "fetch_table",
            "ui:hidden": True,
            "x-category": "Schemas & Tables",
            "x-is-trigger": False,
            "x-display-name": "Fetch Table",
        },
        title="Fetch Table",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to describe")


# ============================================================================
# Warehouse Operation Configs
# ============================================================================


class SnowflakeListWarehousesConfig(BaseModel):
    """List available compute warehouses."""

    operation: Literal["list_warehouses"] = Field(
        "list_warehouses",
        json_schema_extra={
            "const": "list_warehouses",
            "ui:hidden": True,
            "x-category": "Warehouses",
            "x-is-trigger": False,
            "x-display-name": "List Warehouses",
        },
        title="List Warehouses",
    )
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


class SnowflakeCreateWarehouseConfig(BaseModel):
    """Create (or replace) a compute warehouse."""

    operation: Literal["create_warehouse"] = Field(
        "create_warehouse",
        json_schema_extra={
            "const": "create_warehouse",
            "x-creates-resource": True,
            "x-resource-type": "snowflake_warehouse",
            "ui:hidden": True,
            "x-category": "Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Create Warehouse",
        },
        title="Create Warehouse",
    )
    name: str = Field(..., title="Name", description="Name of the warehouse to create")
    warehouse_size: Optional[str] = Field(
        None,
        title="Size",
        description="Warehouse size",
        json_schema_extra={
            "enum": ["XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "XXLARGE"],
            "x-enum-searchable": True,
        },
    )
    auto_suspend: Optional[str] = Field(
        None,
        title="Auto-Suspend (seconds)",
        description="Seconds of inactivity before auto-suspend",
    )


class SnowflakeResumeWarehouseConfig(BaseModel):
    """Resume a suspended warehouse."""

    operation: Literal["resume_warehouse"] = Field(
        "resume_warehouse",
        json_schema_extra={
            "const": "resume_warehouse",
            "ui:hidden": True,
            "x-category": "Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Resume Warehouse",
        },
        title="Resume Warehouse",
    )
    name: str = Field(
        ...,
        title="Warehouse",
        description="The warehouse to resume",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a warehouse name",
            }
        },
    )


class SnowflakeSuspendWarehouseConfig(BaseModel):
    """Suspend a warehouse to stop credit usage."""

    operation: Literal["suspend_warehouse"] = Field(
        "suspend_warehouse",
        json_schema_extra={
            "const": "suspend_warehouse",
            "ui:hidden": True,
            "x-category": "Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Suspend Warehouse",
        },
        title="Suspend Warehouse",
    )
    name: str = Field(
        ...,
        title="Warehouse",
        description="The warehouse to suspend",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a warehouse name",
            }
        },
    )


class SnowflakeAbortWarehouseConfig(BaseModel):
    """Abort all running / queued queries on a warehouse."""

    operation: Literal["abort_warehouse"] = Field(
        "abort_warehouse",
        json_schema_extra={
            "const": "abort_warehouse",
            "ui:hidden": True,
            "x-category": "Warehouses",
            "x-is-trigger": False,
            "x-display-name": "Abort Warehouse Queries",
        },
        title="Abort Warehouse Queries",
    )
    name: str = Field(
        ...,
        title="Warehouse",
        description="The warehouse whose queries to abort",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a warehouse name",
            }
        },
    )


# ============================================================================
# Task Operation Configs
# ============================================================================


class SnowflakeListTasksConfig(BaseModel):
    """List scheduled tasks in a schema."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks",
        json_schema_extra={
            "const": "list_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Tasks",
        },
        title="List Tasks",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    root_only: Optional[str] = Field(
        "false",
        title="Root Tasks Only",
        description="List only root tasks",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class SnowflakeCreateTaskConfig(BaseModel):
    """Create a scheduled SQL task."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the task to create")
    definition: str = Field(
        ...,
        title="SQL Definition",
        description="The SQL the task runs each time it fires",
        json_schema_extra={"ui:widget": "textarea"},
    )
    warehouse: Optional[str] = Field(
        None, title="Warehouse", description="Warehouse the task runs on"
    )
    task_schedule: Optional[str] = Field(
        None,
        title="Schedule",
        description="Schedule, e.g. '5 MINUTE' or 'USING CRON 0 9 * * * UTC'",
    )


class SnowflakeExecuteTaskConfig(BaseModel):
    """Trigger an immediate manual run of a task."""

    operation: Literal["execute_task"] = Field(
        "execute_task",
        json_schema_extra={
            "const": "execute_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Execute Task",
        },
        title="Execute Task",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to execute")


class SnowflakeResumeTaskConfig(BaseModel):
    """Resume (un-suspend) a task."""

    operation: Literal["resume_task"] = Field(
        "resume_task",
        json_schema_extra={
            "const": "resume_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Resume Task",
        },
        title="Resume Task",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to resume")


class SnowflakeSuspendTaskConfig(BaseModel):
    """Pause an active task."""

    operation: Literal["suspend_task"] = Field(
        "suspend_task",
        json_schema_extra={
            "const": "suspend_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Suspend Task",
        },
        title="Suspend Task",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to suspend")


class SnowflakeTaskHistoryConfig(BaseModel):
    """List completed task graph runs (status / timing)."""

    operation: Literal["task_history"] = Field(
        "task_history",
        json_schema_extra={
            "const": "task_history",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Task Run History",
        },
        title="List Task Run History",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task name")


# ============================================================================
# User / Role Operation Configs
# ============================================================================


class SnowflakeListUsersConfig(BaseModel):
    """List Snowflake account users."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users & Roles",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


class SnowflakeCreateUserConfig(BaseModel):
    """Create a new user account."""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "ui:hidden": True,
            "x-category": "Users & Roles",
            "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    name: str = Field(..., title="Name", description="Login name of the user to create")
    email: Optional[str] = Field(
        None, title="Email", description="Email address for the user"
    )
    default_role: Optional[str] = Field(
        None, title="Default Role", description="The user's default role"
    )


class SnowflakeDeleteUserConfig(BaseModel):
    """Drop a named user."""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "Users & Roles",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    name: str = Field(..., title="User", description="The user to drop")


class SnowflakeListRolesConfig(BaseModel):
    """List account roles."""

    operation: Literal["list_roles"] = Field(
        "list_roles",
        json_schema_extra={
            "const": "list_roles",
            "ui:hidden": True,
            "x-category": "Users & Roles",
            "x-is-trigger": False,
            "x-display-name": "List Roles",
        },
        title="List Roles",
    )
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


# ============================================================================
# Stage Operation Config
# ============================================================================


class SnowflakeListStagesConfig(BaseModel):
    """List named stages (for file / data loading)."""

    operation: Literal["list_stages"] = Field(
        "list_stages",
        json_schema_extra={
            "const": "list_stages",
            "ui:hidden": True,
            "x-category": "Stages",
            "x-is-trigger": False,
            "x-display-name": "List Stages",
        },
        title="List Stages",
    )
    database: str = Field(..., title="Database", description="The database name")
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(
        None, title="Like", description="Case-insensitive name pattern filter"
    )


# ============================================================================
# Trigger Operation Config (poll-based)
# ============================================================================


class SnowflakeOnQueryResultsConfig(PollTriggerConfigBase):
    """Poll a user-supplied SQL query on a schedule and emit only NEW rows.

    Snowflake has no outbound webhooks, so this trigger is polling-based: a
    Cloudflare cron schedule POSTs the node's webhook URL (a wake-up signal),
    execute() runs the query, and cursor-column dedup emits only rows not seen
    on a previous poll. Webhook/schedule provisioning, teardown, and the
    resolve-payload short-circuit come from ScheduledPollTriggerMixin; the
    persisted cursor high-water-mark lives in node state (workflow_node_state),
    NOT config (a headless poll can't write config back).
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
    statement: str = Field(
        ...,
        title="SQL Query",
        description=(
            "The SELECT to run on each poll. Order by your cursor column so new "
            "rows are detected, e.g. SELECT id, email FROM signups ORDER BY id"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    cursor_column: str = Field(
        ...,
        title="Cursor Column",
        description=(
            "A monotonically increasing column (timestamp or id) used to detect "
            "and dedupe new rows, e.g. 'ID' or 'CREATED_AT'. Rows whose cursor "
            "value is <= the last seen value are skipped."
        ),
        json_schema_extra={"placeholder": "ID"},
    )
    warehouse: Optional[str] = Field(
        None,
        title="Warehouse",
        description="Compute warehouse to run the query on",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "warehouse",
                "placeholder": "Select a warehouse...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a warehouse name",
            }
        },
    )
    database: Optional[str] = Field(
        None,
        title="Database",
        description="Database context for the query",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a database name",
            }
        },
    )
    schema_name: Optional[str] = Field(
        None, title="Schema", description="Schema context for the query"
    )
    role: Optional[str] = Field(
        None,
        title="Role",
        description="Role to run the query as",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "role",
                "placeholder": "Select a role...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a role name",
            }
        },
    )


# ============================================================================
# Discriminated Union
# ============================================================================


# ============================================================================
# Generated control-plane operation registry (full Snowflake REST API v2)
# ============================================================================
# Additive to the hand-written ops above: full CRUD + resource actions for every
# control-plane resource, generated from Snowflake's official OpenAPI specs. Each
# block below defines Pydantic config classes + module-level handlers
# `async def _fn(node, c, account, token)` and registers them into these two
# collections; the union and execute() dispatch pick them up automatically. Op
# names are unique across the whole node (no collision with the hand-written ops).
SNOWFLAKE_OPERATION_CONFIGS: List[type] = []
SNOWFLAKE_OPERATION_HANDLERS: Dict[str, Any] = {}

# ---- account ----
class SnowflakeListAccountsConfig(BaseModel):
    """List the accessible accounts in the organization."""

    operation: Literal["list_accounts"] = Field(
        "list_accounts",
        json_schema_extra={
            "const": "list_accounts", "ui:hidden": True, "x-category": "Account",
            "x-is-trigger": False, "x-display-name": "List Accounts",
        },
        title="List Accounts",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    history: Optional[str] = Field(
        None, title="History", description="Include dropped accounts that have not yet been purged",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateAccountConfig(BaseModel):
    """Create an account in the organization."""

    operation: Literal["create_account"] = Field(
        "create_account",
        json_schema_extra={
            "const": "create_account", "ui:hidden": True, "x-category": "Account",
            "x-is-trigger": False, "x-display-name": "Create Account",
        },
        title="Create Account",
    )
    name: str = Field(..., title="Name", description="Name that identifies the account within the organization")
    edition: str = Field(
        ..., title="Edition", description="Snowflake Edition of the account",
        json_schema_extra={"enum": ["STANDARD", "ENTERPRISE", "BUSINESS_CRITICAL"], "x-enum-searchable": True},
    )
    admin_name: str = Field(..., title="Admin Name", description="Name of the account administrator")
    email: str = Field(..., title="Email", description="Email address of the account administrator")
    region_group: Optional[str] = Field(None, title="Region Group", description="Region group where the account is located")
    region: Optional[str] = Field(None, title="Region", description="Snowflake Region where the account is located")
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the account")
    admin_password: Optional[str] = Field(None, title="Admin Password", description="Password for the account administrator")
    admin_rsa_public_key: Optional[str] = Field(None, title="Admin RSA Public Key", description="RSA public key for the account administrator")
    admin_user_type: Optional[str] = Field(None, title="Admin User Type", description="User type of the account administrator")
    first_name: Optional[str] = Field(None, title="First Name", description="First name of the account administrator")
    last_name: Optional[str] = Field(None, title="Last Name", description="Last name of the account administrator")
    must_change_password: Optional[str] = Field(
        None, title="Must Change Password", description="Require the administrator to change the password at next login",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    polaris: Optional[str] = Field(
        None, title="Polaris", description="Whether the account is a Polaris account",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeDeleteAccountConfig(BaseModel):
    """Delete an account."""

    operation: Literal["delete_account"] = Field(
        "delete_account",
        json_schema_extra={
            "const": "delete_account", "ui:hidden": True, "x-category": "Account",
            "x-is-trigger": False, "x-display-name": "Delete Account",
        },
        title="Delete Account",
    )
    name: str = Field(..., title="Account", description="The account to delete")
    grace_period_in_days: str = Field(
        ..., title="Grace Period (Days)",
        description="Number of days during which the account can be restored (3-90)",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the account is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropAccountConfig(BaseModel):
    """Restore a dropped account that is still within its grace period."""

    operation: Literal["undrop_account"] = Field(
        "undrop_account",
        json_schema_extra={
            "const": "undrop_account", "ui:hidden": True, "x-category": "Account",
            "x-is-trigger": False, "x-display-name": "Undrop Account",
        },
        title="Undrop Account",
    )
    name: str = Field(..., title="Account", description="The dropped account to restore")


async def _list_accounts(node, c, account, token):
    params = {"like": c.like, "showLimit": c.show_limit, "history": _sf_bool(c.history)}
    return await node._request(account, token, "GET", "/accounts", params=params, action_name="list_accounts")


async def _create_account(node, c, account, token):
    body = {
        "name": c.name, "edition": c.edition, "admin_name": c.admin_name, "email": c.email,
        "region_group": c.region_group, "region": c.region, "comment": c.comment,
        "admin_password": c.admin_password, "admin_rsa_public_key": c.admin_rsa_public_key,
        "admin_user_type": c.admin_user_type, "first_name": c.first_name, "last_name": c.last_name,
        "must_change_password": _sf_bool(c.must_change_password), "polaris": _sf_bool(c.polaris),
    }
    return await node._request(account, token, "POST", "/accounts", json_body=body, action_name="create_account")


async def _delete_account(node, c, account, token):
    ep = f"/accounts/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists), "gracePeriodInDays": _sf_int(c.grace_period_in_days)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_account")


async def _undrop_account(node, c, account, token):
    ep = f"/accounts/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_account")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListAccountsConfig,
    SnowflakeCreateAccountConfig,
    SnowflakeDeleteAccountConfig,
    SnowflakeUndropAccountConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_accounts": _list_accounts,
    "create_account": _create_account,
    "delete_account": _delete_account,
    "undrop_account": _undrop_account,
})


# ---- alert.py ----
class SnowflakeListAlertsConfig(BaseModel):
    """List alerts in a schema."""

    operation: Literal["list_alerts"] = Field(
        "list_alerts",
        json_schema_extra={
            "const": "list_alerts", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "List Alerts",
        },
        title="List Alerts",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateAlertConfig(BaseModel):
    """Create an alert in a schema."""

    operation: Literal["create_alert"] = Field(
        "create_alert",
        json_schema_extra={
            "const": "create_alert", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Create Alert",
        },
        title="Create Alert",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the alert to create")
    condition: str = Field(..., title="Condition", description="SQL statement evaluated to decide whether to trigger the alert")
    action: str = Field(..., title="Action", description="SQL statement executed when the alert is triggered")
    warehouse: Optional[str] = Field(None, title="Warehouse", description="The warehouse the alert runs in")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the alert")
    schedule_type: Optional[str] = Field(
        None, title="Schedule Type", description="Type of schedule the alert runs under",
        json_schema_extra={"enum": ["CRON_TYPE", "MINUTES_TYPE"], "x-enum-searchable": True},
    )
    cron_expr: Optional[str] = Field(None, title="Cron Expression", description="Cron expression for a CRON_TYPE schedule")
    timezone: Optional[str] = Field(None, title="Timezone", description="Time zone for a CRON_TYPE schedule")
    minutes: Optional[str] = Field(None, title="Minutes", description="Interval in minutes for a MINUTES_TYPE schedule")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the alert already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchAlertConfig(BaseModel):
    """Fetch a single alert's definition."""

    operation: Literal["fetch_alert"] = Field(
        "fetch_alert",
        json_schema_extra={
            "const": "fetch_alert", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Fetch Alert",
        },
        title="Fetch Alert",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to fetch")


class SnowflakeDeleteAlertConfig(BaseModel):
    """Drop an alert."""

    operation: Literal["delete_alert"] = Field(
        "delete_alert",
        json_schema_extra={
            "const": "delete_alert", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Delete Alert",
        },
        title="Delete Alert",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the alert is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneAlertConfig(BaseModel):
    """Clone an alert into a (possibly different) schema."""

    operation: Literal["clone_alert"] = Field(
        "clone_alert",
        json_schema_extra={
            "const": "clone_alert", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Clone Alert",
        },
        title="Clone Alert",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Alert", description="The alert to clone")
    target_name: str = Field(..., title="New Name", description="Name of the newly created alert")
    target_database: str = Field(..., title="Target Database", description="Database of the newly created alert")
    target_schema: str = Field(..., title="Target Schema", description="Schema of the newly created alert")
    point_of_time_reference: Optional[str] = Field(
        None, title="Point Of Time Reference", description="Relation to the point of time for Time Travel",
        json_schema_extra={"enum": ["at", "before"], "x-enum-searchable": True},
    )
    point_of_time_timestamp: Optional[str] = Field(None, title="Timestamp", description="Timestamp point of time (e.g. TO_TIMESTAMP(1749423600))")
    point_of_time_offset: Optional[str] = Field(None, title="Offset", description="Offset in seconds from now, form -N (e.g. -120)")
    point_of_time_statement: Optional[str] = Field(None, title="Statement", description="Query ID to use as the reference point")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeExecuteAlertConfig(BaseModel):
    """Execute an alert immediately."""

    operation: Literal["execute_alert"] = Field(
        "execute_alert",
        json_schema_extra={
            "const": "execute_alert", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Execute Alert",
        },
        title="Execute Alert",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to execute")


class SnowflakeSetAlertTagsConfig(BaseModel):
    """Set a tag on an alert."""

    operation: Literal["set_alert_tags"] = Field(
        "set_alert_tags",
        json_schema_extra={
            "const": "set_alert_tags", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Set Alert Tags",
        },
        title="Set Alert Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the alert is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetAlertTagsConfig(BaseModel):
    """Unset a tag from an alert."""

    operation: Literal["unset_alert_tags"] = Field(
        "unset_alert_tags",
        json_schema_extra={
            "const": "unset_alert_tags", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Unset Alert Tags",
        },
        title="Unset Alert Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the alert is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetAlertTagsConfig(BaseModel):
    """Get the tag assignments for an alert (requires an active warehouse)."""

    operation: Literal["get_alert_tags"] = Field(
        "get_alert_tags",
        json_schema_extra={
            "const": "get_alert_tags", "ui:hidden": True, "x-category": "Alerts",
            "x-is-trigger": False, "x-display-name": "Get Alert Tags",
        },
        title="Get Alert Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Alert", description="The alert to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _build_alert_schedule(c):
    if not c.schedule_type:
        return None
    schedule = {"schedule_type": c.schedule_type}
    if c.cron_expr:
        schedule["cron_expr"] = c.cron_expr
    if c.timezone:
        schedule["timezone"] = c.timezone
    if c.minutes:
        schedule["minutes"] = _sf_int(c.minutes)
    return schedule


def _build_alert_point_of_time(c):
    if c.point_of_time_timestamp:
        return {"point_of_time_type": "timestamp", "reference": c.point_of_time_reference,
                "timestamp": c.point_of_time_timestamp}
    if c.point_of_time_offset:
        return {"point_of_time_type": "offset", "reference": c.point_of_time_reference,
                "offset": c.point_of_time_offset}
    if c.point_of_time_statement:
        return {"point_of_time_type": "statement", "reference": c.point_of_time_reference,
                "statement": c.point_of_time_statement}
    return None


async def _list_alerts(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/alerts"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_alerts")


async def _create_alert(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/alerts"
    body = {"name": c.name, "condition": c.condition, "action": c.action,
            "warehouse": c.warehouse, "comment": c.comment, "schedule": _build_alert_schedule(c)}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_alert")


async def _fetch_alert(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_alert")


async def _delete_alert(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_alert")


async def _clone_alert(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}:clone"
    params = {"createMode": c.create_mode, "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    body = {"name": c.target_name, "point_of_time": _build_alert_point_of_time(c)}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_alert")


async def _execute_alert(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}:execute"
    return await node._request(account, token, "POST", ep, action_name="execute_alert")


async def _set_alert_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_alert_tags")


async def _unset_alert_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_alert_tags")


async def _get_alert_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/alerts/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_alert_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListAlertsConfig,
    SnowflakeCreateAlertConfig,
    SnowflakeFetchAlertConfig,
    SnowflakeDeleteAlertConfig,
    SnowflakeCloneAlertConfig,
    SnowflakeExecuteAlertConfig,
    SnowflakeSetAlertTagsConfig,
    SnowflakeUnsetAlertTagsConfig,
    SnowflakeGetAlertTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_alerts": _list_alerts,
    "create_alert": _create_alert,
    "fetch_alert": _fetch_alert,
    "delete_alert": _delete_alert,
    "clone_alert": _clone_alert,
    "execute_alert": _execute_alert,
    "set_alert_tags": _set_alert_tags,
    "unset_alert_tags": _unset_alert_tags,
    "get_alert_tags": _get_alert_tags,
})


# ---- api_integration.py ----
class SnowflakeListApiIntegrationsConfig(BaseModel):
    """List API integrations in the account."""

    operation: Literal["list_api_integrations"] = Field(
        "list_api_integrations",
        json_schema_extra={
            "const": "list_api_integrations", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "List API Integrations",
        },
        title="List API Integrations",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateApiIntegrationConfig(BaseModel):
    """Create an API integration."""

    operation: Literal["create_api_integration"] = Field(
        "create_api_integration",
        json_schema_extra={
            "const": "create_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Create API Integration",
        },
        title="Create API Integration",
    )
    name: str = Field(..., title="Name", description="Name of the API integration to create")
    hook_type: str = Field(
        ..., title="Hook Type", description="Type of API hook",
        json_schema_extra={"enum": ["AWS", "AZURE", "GC", "GIT"], "x-enum-searchable": True},
    )
    api_provider: Optional[str] = Field(
        None, title="API Provider",
        description="Provider for AWS/Azure/GC hooks (e.g. AWS_API_GATEWAY, AZURE_API_MANAGEMENT, GOOGLE_API_GATEWAY)",
    )
    api_aws_role_arn: Optional[str] = Field(None, title="AWS Role ARN", description="ARN of the IAM role (AWS hook)")
    api_key: Optional[str] = Field(None, title="API Key", description="Subscription key used to identify API clients")
    azure_tenant_id: Optional[str] = Field(None, title="Azure Tenant ID", description="Office 365 tenant ID (Azure hook)")
    azure_ad_application_id: Optional[str] = Field(
        None, title="Azure AD Application ID", description="Azure Active Directory application ID (Azure hook)")
    google_audience: Optional[str] = Field(
        None, title="Google Audience", description="Audience claim for the Google API Gateway (GC hook)")
    allow_any_secret: Optional[str] = Field(
        None, title="Allow Any Secret",
        description="Allow any Snowflake secret when accessing the Git repository (GIT hook)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allowed_authentication_secrets: Optional[str] = Field(
        None, title="Allowed Authentication Secrets",
        description="Comma-separated fully-qualified secret names usable when accessing the Git repository (GIT hook)")
    allowed_api_authentication_integrations: Optional[str] = Field(
        None, title="Allowed API Authentication Integrations",
        description="Comma-separated security integration names usable when accessing the Git repository (GIT hook)")
    api_allowed_prefixes: Optional[str] = Field(
        None, title="API Allowed Prefixes",
        description="Comma-separated endpoints/resources Snowflake can access")
    api_blocked_prefixes: Optional[str] = Field(
        None, title="API Blocked Prefixes",
        description="Comma-separated endpoints/resources not allowed to be called from Snowflake")
    enabled: Optional[str] = Field(
        "true", title="Enabled", description="Whether the API integration is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the API integration")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the API integration already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchApiIntegrationConfig(BaseModel):
    """Fetch a single API integration's definition."""

    operation: Literal["fetch_api_integration"] = Field(
        "fetch_api_integration",
        json_schema_extra={
            "const": "fetch_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Fetch API Integration",
        },
        title="Fetch API Integration",
    )
    name: str = Field(..., title="API Integration", description="The API integration to fetch")


class SnowflakeCreateOrAlterApiIntegrationConfig(BaseModel):
    """Create an API integration, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_api_integration"] = Field(
        "create_or_alter_api_integration",
        json_schema_extra={
            "const": "create_or_alter_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Create or Alter API Integration",
        },
        title="Create or Alter API Integration",
    )
    name: str = Field(..., title="Name", description="Name of the API integration")
    hook_type: str = Field(
        ..., title="Hook Type", description="Type of API hook",
        json_schema_extra={"enum": ["AWS", "AZURE", "GC", "GIT"], "x-enum-searchable": True},
    )
    api_provider: Optional[str] = Field(
        None, title="API Provider",
        description="Provider for AWS/Azure/GC hooks (e.g. AWS_API_GATEWAY, AZURE_API_MANAGEMENT, GOOGLE_API_GATEWAY)",
    )
    api_aws_role_arn: Optional[str] = Field(None, title="AWS Role ARN", description="ARN of the IAM role (AWS hook)")
    api_key: Optional[str] = Field(None, title="API Key", description="Subscription key used to identify API clients")
    azure_tenant_id: Optional[str] = Field(None, title="Azure Tenant ID", description="Office 365 tenant ID (Azure hook)")
    azure_ad_application_id: Optional[str] = Field(
        None, title="Azure AD Application ID", description="Azure Active Directory application ID (Azure hook)")
    google_audience: Optional[str] = Field(
        None, title="Google Audience", description="Audience claim for the Google API Gateway (GC hook)")
    allow_any_secret: Optional[str] = Field(
        None, title="Allow Any Secret",
        description="Allow any Snowflake secret when accessing the Git repository (GIT hook)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allowed_authentication_secrets: Optional[str] = Field(
        None, title="Allowed Authentication Secrets",
        description="Comma-separated fully-qualified secret names usable when accessing the Git repository (GIT hook)")
    allowed_api_authentication_integrations: Optional[str] = Field(
        None, title="Allowed API Authentication Integrations",
        description="Comma-separated security integration names usable when accessing the Git repository (GIT hook)")
    api_allowed_prefixes: Optional[str] = Field(
        None, title="API Allowed Prefixes",
        description="Comma-separated endpoints/resources Snowflake can access")
    api_blocked_prefixes: Optional[str] = Field(
        None, title="API Blocked Prefixes",
        description="Comma-separated endpoints/resources not allowed to be called from Snowflake")
    enabled: Optional[str] = Field(
        "true", title="Enabled", description="Whether the API integration is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the API integration")


class SnowflakeDeleteApiIntegrationConfig(BaseModel):
    """Drop an API integration."""

    operation: Literal["delete_api_integration"] = Field(
        "delete_api_integration",
        json_schema_extra={
            "const": "delete_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Delete API Integration",
        },
        title="Delete API Integration",
    )
    name: str = Field(..., title="API Integration", description="The API integration to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the API integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsApiIntegrationConfig(BaseModel):
    """Set a tag on an API integration."""

    operation: Literal["set_tags_api_integration"] = Field(
        "set_tags_api_integration",
        json_schema_extra={
            "const": "set_tags_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Set Tags on API Integration",
        },
        title="Set Tags on API Integration",
    )
    name: str = Field(..., title="API Integration", description="The API integration to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the API integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsApiIntegrationConfig(BaseModel):
    """Unset a tag from an API integration."""

    operation: Literal["unset_tags_api_integration"] = Field(
        "unset_tags_api_integration",
        json_schema_extra={
            "const": "unset_tags_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Unset Tags from API Integration",
        },
        title="Unset Tags from API Integration",
    )
    name: str = Field(..., title="API Integration", description="The API integration to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the API integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsApiIntegrationConfig(BaseModel):
    """Get the tag assignments for an API integration."""

    operation: Literal["get_tags_api_integration"] = Field(
        "get_tags_api_integration",
        json_schema_extra={
            "const": "get_tags_api_integration", "ui:hidden": True, "x-category": "API Integrations",
            "x-is-trigger": False, "x-display-name": "Get Tags on API Integration",
        },
        title="Get Tags on API Integration",
    )
    name: str = Field(..., title="API Integration", description="The API integration whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_csv(value):
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _sf_api_integration_body(c):
    hook = {"type": c.hook_type}
    for key, val in (
        ("api_provider", c.api_provider),
        ("api_aws_role_arn", c.api_aws_role_arn),
        ("api_key", c.api_key),
        ("azure_tenant_id", c.azure_tenant_id),
        ("azure_ad_application_id", c.azure_ad_application_id),
        ("google_audience", c.google_audience),
    ):
        if val is not None:
            hook[key] = val
    if _sf_bool(c.allow_any_secret) is not None:
        hook["allow_any_secret"] = _sf_bool(c.allow_any_secret)
    if _sf_csv(c.allowed_authentication_secrets) is not None:
        hook["allowed_authentication_secrets"] = _sf_csv(c.allowed_authentication_secrets)
    if _sf_csv(c.allowed_api_authentication_integrations) is not None:
        hook["allowed_api_authentication_integrations"] = _sf_csv(c.allowed_api_authentication_integrations)
    return {
        "name": c.name,
        "api_hook": hook,
        "api_allowed_prefixes": _sf_csv(c.api_allowed_prefixes),
        "api_blocked_prefixes": _sf_csv(c.api_blocked_prefixes),
        "enabled": _sf_bool(c.enabled),
        "comment": c.comment,
    }


async def _list_api_integrations(node, c, account, token):
    params = {"like": c.like}
    return await node._request(account, token, "GET", "/api-integrations", params=params, action_name="list_api_integrations")


async def _create_api_integration(node, c, account, token):
    body = _sf_api_integration_body(c)
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/api-integrations", params=params, json_body=body, action_name="create_api_integration")


async def _fetch_api_integration(node, c, account, token):
    return await node._request(account, token, "GET", f"/api-integrations/{c.name}", action_name="fetch_api_integration")


async def _create_or_alter_api_integration(node, c, account, token):
    body = _sf_api_integration_body(c)
    return await node._request(account, token, "PUT", f"/api-integrations/{c.name}", json_body=body, action_name="create_or_alter_api_integration")


async def _delete_api_integration(node, c, account, token):
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", f"/api-integrations/{c.name}", params=params, action_name="delete_api_integration")


async def _set_tags_api_integration(node, c, account, token):
    ep = f"/api-integrations/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_api_integration")


async def _unset_tags_api_integration(node, c, account, token):
    ep = f"/api-integrations/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_api_integration")


async def _get_tags_api_integration(node, c, account, token):
    ep = f"/api-integrations/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_api_integration")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListApiIntegrationsConfig,
    SnowflakeCreateApiIntegrationConfig,
    SnowflakeFetchApiIntegrationConfig,
    SnowflakeCreateOrAlterApiIntegrationConfig,
    SnowflakeDeleteApiIntegrationConfig,
    SnowflakeSetTagsApiIntegrationConfig,
    SnowflakeUnsetTagsApiIntegrationConfig,
    SnowflakeGetTagsApiIntegrationConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_api_integrations": _list_api_integrations,
    "create_api_integration": _create_api_integration,
    "fetch_api_integration": _fetch_api_integration,
    "create_or_alter_api_integration": _create_or_alter_api_integration,
    "delete_api_integration": _delete_api_integration,
    "set_tags_api_integration": _set_tags_api_integration,
    "unset_tags_api_integration": _unset_tags_api_integration,
    "get_tags_api_integration": _get_tags_api_integration,
})


# ---- artifact_repository.py ----
class SnowflakeListArtifactRepositoriesConfig(BaseModel):
    """List artifact repositories in a schema."""

    operation: Literal["list_artifact_repositories"] = Field(
        "list_artifact_repositories",
        json_schema_extra={
            "const": "list_artifact_repositories", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "List Artifact Repositories",
        },
        title="List Artifact Repositories",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateArtifactRepositoryConfig(BaseModel):
    """Create an artifact repository in a schema."""

    operation: Literal["create_artifact_repository"] = Field(
        "create_artifact_repository",
        json_schema_extra={
            "const": "create_artifact_repository", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "Create Artifact Repository",
        },
        title="Create Artifact Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the artifact repository to create")
    type: str = Field(
        "PIP", title="Type", description="Type of the repository (only PIP is supported)",
        json_schema_extra={"enum": ["PIP"], "x-enum-searchable": True},
    )
    api_integration: str = Field(..., title="API Integration", description="Link to an API integration object")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the artifact repository")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the artifact repository already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchArtifactRepositoryConfig(BaseModel):
    """Fetch a single artifact repository's definition."""

    operation: Literal["fetch_artifact_repository"] = Field(
        "fetch_artifact_repository",
        json_schema_extra={
            "const": "fetch_artifact_repository", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "Fetch Artifact Repository",
        },
        title="Fetch Artifact Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Artifact Repository", description="The artifact repository to fetch")


class SnowflakeCreateOrAlterArtifactRepositoryConfig(BaseModel):
    """Create an artifact repository, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_artifact_repository"] = Field(
        "create_or_alter_artifact_repository",
        json_schema_extra={
            "const": "create_or_alter_artifact_repository", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "Create or Alter Artifact Repository",
        },
        title="Create or Alter Artifact Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the artifact repository")
    type: str = Field(
        "PIP", title="Type", description="Type of the repository (only PIP is supported)",
        json_schema_extra={"enum": ["PIP"], "x-enum-searchable": True},
    )
    api_integration: str = Field(..., title="API Integration", description="Link to an API integration object")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the artifact repository")


class SnowflakeDeleteArtifactRepositoryConfig(BaseModel):
    """Drop an artifact repository."""

    operation: Literal["delete_artifact_repository"] = Field(
        "delete_artifact_repository",
        json_schema_extra={
            "const": "delete_artifact_repository", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "Delete Artifact Repository",
        },
        title="Delete Artifact Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Artifact Repository", description="The artifact repository to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the artifact repository is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRenameArtifactRepositoryConfig(BaseModel):
    """Rename an artifact repository to a new identifier."""

    operation: Literal["rename_artifact_repository"] = Field(
        "rename_artifact_repository",
        json_schema_extra={
            "const": "rename_artifact_repository", "ui:hidden": True, "x-category": "Artifact Repositories",
            "x-is-trigger": False, "x-display-name": "Rename Artifact Repository",
        },
        title="Rename Artifact Repository",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Artifact Repository", description="The artifact repository to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed artifact repository")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the artifact repository is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_artifact_repositories(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_artifact_repositories")


async def _create_artifact_repository(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories"
    body = {"name": c.name, "type": c.type, "api_integration": c.api_integration, "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_artifact_repository")


async def _fetch_artifact_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_artifact_repository")


async def _create_or_alter_artifact_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories/{c.name}"
    body = {"name": c.name, "type": c.type, "api_integration": c.api_integration, "comment": c.comment}
    return await node._request(account, token, "PUT", ep, json_body=body, action_name="create_or_alter_artifact_repository")


async def _delete_artifact_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_artifact_repository")


async def _rename_artifact_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/artifact-repositories/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_artifact_repository")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListArtifactRepositoriesConfig,
    SnowflakeCreateArtifactRepositoryConfig,
    SnowflakeFetchArtifactRepositoryConfig,
    SnowflakeCreateOrAlterArtifactRepositoryConfig,
    SnowflakeDeleteArtifactRepositoryConfig,
    SnowflakeRenameArtifactRepositoryConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_artifact_repositories": _list_artifact_repositories,
    "create_artifact_repository": _create_artifact_repository,
    "fetch_artifact_repository": _fetch_artifact_repository,
    "create_or_alter_artifact_repository": _create_or_alter_artifact_repository,
    "delete_artifact_repository": _delete_artifact_repository,
    "rename_artifact_repository": _rename_artifact_repository,
})


# ---- catalog_integration.py ----
class SnowflakeListCatalogIntegrationsConfig(BaseModel):
    """List catalog integrations in the account."""

    operation: Literal["list_catalog_integrations"] = Field(
        "list_catalog_integrations",
        json_schema_extra={
            "const": "list_catalog_integrations", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "List Catalog Integrations",
        },
        title="List Catalog Integrations",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateCatalogIntegrationConfig(BaseModel):
    """Create a catalog integration."""

    operation: Literal["create_catalog_integration"] = Field(
        "create_catalog_integration",
        json_schema_extra={
            "const": "create_catalog_integration", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Create Catalog Integration",
        },
        title="Create Catalog Integration",
    )
    name: str = Field(..., title="Name", description="Name of the catalog integration to create")
    catalog_source: str = Field(
        ..., title="Catalog Source", description="Type of external catalog",
        json_schema_extra={"enum": ["GLUE", "OBJECT_STORE", "POLARIS"], "x-enum-searchable": True},
    )
    table_format: str = Field(
        "ICEBERG", title="Table Format", description="Table format of the catalog",
        json_schema_extra={"enum": ["ICEBERG"], "x-enum-searchable": True},
    )
    enabled: Optional[str] = Field(
        "true", title="Enabled", description="Whether this catalog integration is available for Iceberg tables",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the catalog integration")
    glue_aws_role_arn: Optional[str] = Field(None, title="Glue AWS Role ARN", description="ARN for the AWS role to assume (GLUE)")
    glue_catalog_id: Optional[str] = Field(None, title="Glue Catalog ID", description="Glue catalog id (GLUE)")
    glue_region: Optional[str] = Field(None, title="Glue Region", description="AWS region of the Glue catalog (GLUE)")
    catalog_namespace: Optional[str] = Field(None, title="Catalog Namespace", description="Default catalog namespace (GLUE or POLARIS)")
    rest_catalog_uri: Optional[str] = Field(None, title="REST Catalog URI", description="Polaris account locator URL (POLARIS)")
    rest_warehouse: Optional[str] = Field(None, title="REST Warehouse", description="Name of the catalog to use in Polaris (POLARIS)")
    oauth_client_id: Optional[str] = Field(None, title="OAuth Client ID", description="OAuth2 client id for the Polaris connection (POLARIS)")
    oauth_client_secret: Optional[str] = Field(None, title="OAuth Client Secret", description="OAuth2 client secret for the Polaris connection (POLARIS)")
    oauth_allowed_scopes: Optional[str] = Field(None, title="OAuth Allowed Scopes", description="Comma-separated OAuth token scopes (POLARIS)")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the catalog integration already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchCatalogIntegrationConfig(BaseModel):
    """Fetch a single catalog integration's definition."""

    operation: Literal["fetch_catalog_integration"] = Field(
        "fetch_catalog_integration",
        json_schema_extra={
            "const": "fetch_catalog_integration", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Fetch Catalog Integration",
        },
        title="Fetch Catalog Integration",
    )
    name: str = Field(..., title="Catalog Integration", description="The catalog integration to fetch")


class SnowflakeDeleteCatalogIntegrationConfig(BaseModel):
    """Drop a catalog integration."""

    operation: Literal["delete_catalog_integration"] = Field(
        "delete_catalog_integration",
        json_schema_extra={
            "const": "delete_catalog_integration", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Delete Catalog Integration",
        },
        title="Delete Catalog Integration",
    )
    name: str = Field(..., title="Catalog Integration", description="The catalog integration to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the catalog integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetCatalogIntegrationTagsConfig(BaseModel):
    """Set a tag on a catalog integration."""

    operation: Literal["set_catalog_integration_tags"] = Field(
        "set_catalog_integration_tags",
        json_schema_extra={
            "const": "set_catalog_integration_tags", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Set Catalog Integration Tags",
        },
        title="Set Catalog Integration Tags",
    )
    name: str = Field(..., title="Catalog Integration", description="The catalog integration to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the catalog integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetCatalogIntegrationTagsConfig(BaseModel):
    """Unset a tag from a catalog integration."""

    operation: Literal["unset_catalog_integration_tags"] = Field(
        "unset_catalog_integration_tags",
        json_schema_extra={
            "const": "unset_catalog_integration_tags", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Unset Catalog Integration Tags",
        },
        title="Unset Catalog Integration Tags",
    )
    name: str = Field(..., title="Catalog Integration", description="The catalog integration to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the catalog integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetCatalogIntegrationTagsConfig(BaseModel):
    """Get the tag assignments for a catalog integration (requires an active warehouse)."""

    operation: Literal["get_catalog_integration_tags"] = Field(
        "get_catalog_integration_tags",
        json_schema_extra={
            "const": "get_catalog_integration_tags", "ui:hidden": True, "x-category": "Catalog Integrations",
            "x-is-trigger": False, "x-display-name": "Get Catalog Integration Tags",
        },
        title="Get Catalog Integration Tags",
    )
    name: str = Field(..., title="Catalog Integration", description="The catalog integration whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_catalog_integrations(node, c, account, token):
    params = {"like": c.like}
    return await node._request(account, token, "GET", "/catalog-integrations", params=params, action_name="list_catalog_integrations")


async def _create_catalog_integration(node, c, account, token):
    catalog = {"catalog_source": c.catalog_source}
    if c.catalog_source == "GLUE":
        catalog.update({
            "glue_aws_role_arn": c.glue_aws_role_arn, "glue_catalog_id": c.glue_catalog_id,
            "glue_region": c.glue_region, "catalog_namespace": c.catalog_namespace,
        })
    elif c.catalog_source == "POLARIS":
        rest_config = {"catalog_uri": c.rest_catalog_uri, "warehouse": c.rest_warehouse}
        scopes = [s.strip() for s in c.oauth_allowed_scopes.split(",") if s.strip()] if c.oauth_allowed_scopes else None
        rest_authentication = {
            "type": "OAUTH", "oauth_client_id": c.oauth_client_id,
            "oauth_client_secret": c.oauth_client_secret, "oauth_allowed_scopes": scopes,
        }
        catalog.update({
            "catalog_namespace": c.catalog_namespace, "rest_config": rest_config,
            "rest_authentication": rest_authentication,
        })
    body = {
        "name": c.name, "catalog": catalog, "table_format": c.table_format,
        "enabled": _sf_bool(c.enabled), "comment": c.comment,
    }
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/catalog-integrations", params=params, json_body=body, action_name="create_catalog_integration")


async def _fetch_catalog_integration(node, c, account, token):
    ep = f"/catalog-integrations/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_catalog_integration")


async def _delete_catalog_integration(node, c, account, token):
    ep = f"/catalog-integrations/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_catalog_integration")


async def _set_catalog_integration_tags(node, c, account, token):
    ep = f"/catalog-integrations/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_catalog_integration_tags")


async def _unset_catalog_integration_tags(node, c, account, token):
    ep = f"/catalog-integrations/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_catalog_integration_tags")


async def _get_catalog_integration_tags(node, c, account, token):
    ep = f"/catalog-integrations/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_catalog_integration_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListCatalogIntegrationsConfig,
    SnowflakeCreateCatalogIntegrationConfig,
    SnowflakeFetchCatalogIntegrationConfig,
    SnowflakeDeleteCatalogIntegrationConfig,
    SnowflakeSetCatalogIntegrationTagsConfig,
    SnowflakeUnsetCatalogIntegrationTagsConfig,
    SnowflakeGetCatalogIntegrationTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_catalog_integrations": _list_catalog_integrations,
    "create_catalog_integration": _create_catalog_integration,
    "fetch_catalog_integration": _fetch_catalog_integration,
    "delete_catalog_integration": _delete_catalog_integration,
    "set_catalog_integration_tags": _set_catalog_integration_tags,
    "unset_catalog_integration_tags": _unset_catalog_integration_tags,
    "get_catalog_integration_tags": _get_catalog_integration_tags,
})


# ---- compute_pool.py ----
class SnowflakeListComputePoolsConfig(BaseModel):
    """List compute pools under the account."""

    operation: Literal["list_compute_pools"] = Field(
        "list_compute_pools",
        json_schema_extra={
            "const": "list_compute_pools", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "List Compute Pools",
        },
        title="List Compute Pools",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeCreateComputePoolConfig(BaseModel):
    """Create a compute pool."""

    operation: Literal["create_compute_pool"] = Field(
        "create_compute_pool",
        json_schema_extra={
            "const": "create_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Create Compute Pool",
        },
        title="Create Compute Pool",
    )
    name: str = Field(..., title="Name", description="Name of the compute pool to create")
    instance_family: str = Field(..., title="Instance Family", description="Instance family for the compute pool")
    min_nodes: str = Field(..., title="Min Nodes", description="Minimum number of nodes for the compute pool")
    max_nodes: str = Field(..., title="Max Nodes", description="Maximum number of nodes for the compute pool")
    auto_resume: Optional[str] = Field(
        None, title="Auto Resume",
        description="Whether Snowflake automatically resumes the pool when needed",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_suspend_secs: Optional[str] = Field(None, title="Auto Suspend (secs)", description="Seconds until the pool auto-suspends")
    comment: Optional[str] = Field(None, title="Comment", description="Comment describing the compute pool")
    initially_suspended: Optional[str] = Field(
        None, title="Initially Suspended",
        description="Create the compute pool initially in the suspended state",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the compute pool already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchComputePoolConfig(BaseModel):
    """Fetch a single compute pool's definition."""

    operation: Literal["fetch_compute_pool"] = Field(
        "fetch_compute_pool",
        json_schema_extra={
            "const": "fetch_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Fetch Compute Pool",
        },
        title="Fetch Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to fetch")


class SnowflakeCreateOrAlterComputePoolConfig(BaseModel):
    """Create a compute pool, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_compute_pool"] = Field(
        "create_or_alter_compute_pool",
        json_schema_extra={
            "const": "create_or_alter_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Create or Alter Compute Pool",
        },
        title="Create or Alter Compute Pool",
    )
    name: str = Field(..., title="Name", description="Name of the compute pool")
    instance_family: str = Field(..., title="Instance Family", description="Instance family for the compute pool")
    min_nodes: str = Field(..., title="Min Nodes", description="Minimum number of nodes for the compute pool")
    max_nodes: str = Field(..., title="Max Nodes", description="Maximum number of nodes for the compute pool")
    auto_resume: Optional[str] = Field(
        None, title="Auto Resume",
        description="Whether Snowflake automatically resumes the pool when needed",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_suspend_secs: Optional[str] = Field(None, title="Auto Suspend (secs)", description="Seconds until the pool auto-suspends")
    comment: Optional[str] = Field(None, title="Comment", description="Comment describing the compute pool")


class SnowflakeDeleteComputePoolConfig(BaseModel):
    """Drop a compute pool."""

    operation: Literal["delete_compute_pool"] = Field(
        "delete_compute_pool",
        json_schema_extra={
            "const": "delete_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Delete Compute Pool",
        },
        title="Delete Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the compute pool is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeResumeComputePoolConfig(BaseModel):
    """Resume a suspended compute pool."""

    operation: Literal["resume_compute_pool"] = Field(
        "resume_compute_pool",
        json_schema_extra={
            "const": "resume_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Resume Compute Pool",
        },
        title="Resume Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to resume")


class SnowflakeSuspendComputePoolConfig(BaseModel):
    """Suspend an active compute pool."""

    operation: Literal["suspend_compute_pool"] = Field(
        "suspend_compute_pool",
        json_schema_extra={
            "const": "suspend_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Suspend Compute Pool",
        },
        title="Suspend Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to suspend")


class SnowflakeStopAllServicesInComputePoolDeprecatedConfig(BaseModel):
    """Stop all services on a compute pool (deprecated endpoint)."""

    operation: Literal["stop_all_services_in_compute_pool_deprecated"] = Field(
        "stop_all_services_in_compute_pool_deprecated",
        json_schema_extra={
            "const": "stop_all_services_in_compute_pool_deprecated", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Stop All Services (Deprecated)",
        },
        title="Stop All Services (Deprecated)",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool whose services to stop")


class SnowflakeStopAllServicesInComputePoolConfig(BaseModel):
    """Stop all services on a compute pool."""

    operation: Literal["stop_all_services_in_compute_pool"] = Field(
        "stop_all_services_in_compute_pool",
        json_schema_extra={
            "const": "stop_all_services_in_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Stop All Services",
        },
        title="Stop All Services",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool whose services to stop")


class SnowflakeListComputePoolInstanceFamiliesConfig(BaseModel):
    """List available compute pool instance families."""

    operation: Literal["list_compute_pool_instance_families"] = Field(
        "list_compute_pool_instance_families",
        json_schema_extra={
            "const": "list_compute_pool_instance_families", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "List Instance Families",
        },
        title="List Instance Families",
    )


class SnowflakeSetTagsComputePoolConfig(BaseModel):
    """Set a tag on a compute pool."""

    operation: Literal["set_tags_compute_pool"] = Field(
        "set_tags_compute_pool",
        json_schema_extra={
            "const": "set_tags_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Set Tags on Compute Pool",
        },
        title="Set Tags on Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the compute pool is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsComputePoolConfig(BaseModel):
    """Unset a tag from a compute pool."""

    operation: Literal["unset_tags_compute_pool"] = Field(
        "unset_tags_compute_pool",
        json_schema_extra={
            "const": "unset_tags_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Unset Tags from Compute Pool",
        },
        title="Unset Tags from Compute Pool",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the compute pool is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsComputePoolConfig(BaseModel):
    """Get the tag assignments for a compute pool."""

    operation: Literal["get_tags_compute_pool"] = Field(
        "get_tags_compute_pool",
        json_schema_extra={
            "const": "get_tags_compute_pool", "ui:hidden": True, "x-category": "Compute Pools",
            "x-is-trigger": False, "x-display-name": "Get Compute Pool Tags",
        },
        title="Get Compute Pool Tags",
    )
    name: str = Field(..., title="Compute Pool", description="The compute pool whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_compute_pools(node, c, account, token):
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit}
    return await node._request(account, token, "GET", "/compute-pools", params=params, action_name="list_compute_pools")


async def _create_compute_pool(node, c, account, token):
    body = {"name": c.name, "instance_family": c.instance_family,
            "min_nodes": _sf_int(c.min_nodes), "max_nodes": _sf_int(c.max_nodes),
            "auto_resume": _sf_bool(c.auto_resume), "auto_suspend_secs": _sf_int(c.auto_suspend_secs),
            "comment": c.comment}
    params = {"createMode": c.create_mode, "initiallySuspended": _sf_bool(c.initially_suspended)}
    return await node._request(account, token, "POST", "/compute-pools", params=params, json_body=body, action_name="create_compute_pool")


async def _fetch_compute_pool(node, c, account, token):
    return await node._request(account, token, "GET", f"/compute-pools/{c.name}", action_name="fetch_compute_pool")


async def _create_or_alter_compute_pool(node, c, account, token):
    body = {"name": c.name, "instance_family": c.instance_family,
            "min_nodes": _sf_int(c.min_nodes), "max_nodes": _sf_int(c.max_nodes),
            "auto_resume": _sf_bool(c.auto_resume), "auto_suspend_secs": _sf_int(c.auto_suspend_secs),
            "comment": c.comment}
    return await node._request(account, token, "PUT", f"/compute-pools/{c.name}", json_body=body, action_name="create_or_alter_compute_pool")


async def _delete_compute_pool(node, c, account, token):
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", f"/compute-pools/{c.name}", params=params, action_name="delete_compute_pool")


async def _resume_compute_pool(node, c, account, token):
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:resume", action_name="resume_compute_pool")


async def _suspend_compute_pool(node, c, account, token):
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:suspend", action_name="suspend_compute_pool")


async def _stop_all_services_in_compute_pool_deprecated(node, c, account, token):
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:stopallservices", action_name="stop_all_services_in_compute_pool_deprecated")


async def _stop_all_services_in_compute_pool(node, c, account, token):
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:stop-all-services", action_name="stop_all_services_in_compute_pool")


async def _list_compute_pool_instance_families(node, c, account, token):
    return await node._request(account, token, "GET", "/compute-pools/instance-families", action_name="list_compute_pool_instance_families")


async def _set_tags_compute_pool(node, c, account, token):
    body = [{"name": c.tag_name, "value": c.tag_value}]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:set-tags", params=params, json_body=body, action_name="set_tags_compute_pool")


async def _unset_tags_compute_pool(node, c, account, token):
    body = [{"name": c.tag_name}]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/compute-pools/{c.name}:unset-tags", params=params, json_body=body, action_name="unset_tags_compute_pool")


async def _get_tags_compute_pool(node, c, account, token):
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", f"/compute-pools/{c.name}:get-tags", params=params, action_name="get_tags_compute_pool")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListComputePoolsConfig,
    SnowflakeCreateComputePoolConfig,
    SnowflakeFetchComputePoolConfig,
    SnowflakeCreateOrAlterComputePoolConfig,
    SnowflakeDeleteComputePoolConfig,
    SnowflakeResumeComputePoolConfig,
    SnowflakeSuspendComputePoolConfig,
    SnowflakeStopAllServicesInComputePoolDeprecatedConfig,
    SnowflakeStopAllServicesInComputePoolConfig,
    SnowflakeListComputePoolInstanceFamiliesConfig,
    SnowflakeSetTagsComputePoolConfig,
    SnowflakeUnsetTagsComputePoolConfig,
    SnowflakeGetTagsComputePoolConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_compute_pools": _list_compute_pools,
    "create_compute_pool": _create_compute_pool,
    "fetch_compute_pool": _fetch_compute_pool,
    "create_or_alter_compute_pool": _create_or_alter_compute_pool,
    "delete_compute_pool": _delete_compute_pool,
    "resume_compute_pool": _resume_compute_pool,
    "suspend_compute_pool": _suspend_compute_pool,
    "stop_all_services_in_compute_pool_deprecated": _stop_all_services_in_compute_pool_deprecated,
    "stop_all_services_in_compute_pool": _stop_all_services_in_compute_pool,
    "list_compute_pool_instance_families": _list_compute_pool_instance_families,
    "set_tags_compute_pool": _set_tags_compute_pool,
    "unset_tags_compute_pool": _unset_tags_compute_pool,
    "get_tags_compute_pool": _get_tags_compute_pool,
})


# ---- database.py ----
class SnowflakeCreateDatabaseFromShareConfig(BaseModel):
    """Create a database from a share."""

    operation: Literal["create_database_from_share"] = Field(
        "create_database_from_share",
        json_schema_extra={
            "const": "create_database_from_share", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Create Database from Share",
        },
        title="Create Database from Share",
    )
    name: str = Field(..., title="Name", description="Name of the database to create")
    share: Optional[str] = Field(
        None, title="Share",
        description="ID of the share, in the form '<provider_account>.<share_name>'",
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the database already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCreateDatabaseFromShareDeprecatedConfig(BaseModel):
    """Create a database from a share (deprecated endpoint)."""

    operation: Literal["create_database_from_share_deprecated"] = Field(
        "create_database_from_share_deprecated",
        json_schema_extra={
            "const": "create_database_from_share_deprecated", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Create Database from Share (Deprecated)",
        },
        title="Create Database from Share (Deprecated)",
    )
    name: str = Field(..., title="Name", description="Name of the database to create")
    share: Optional[str] = Field(
        None, title="Share",
        description="ID of the share, in the form '<provider_account>.<share_name>'",
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the database already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCloneDatabaseConfig(BaseModel):
    """Clone an existing database."""

    operation: Literal["clone_database"] = Field(
        "clone_database",
        json_schema_extra={
            "const": "clone_database", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Clone Database",
        },
        title="Clone Database",
    )
    name: str = Field(
        ..., title="Source Database", description="The database to clone",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    new_name: str = Field(..., title="New Name", description="Name of the cloned database")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the cloned database")
    kind: Optional[str] = Field(
        None, title="Kind", description="Database type (deprecated)",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCreateOrAlterDatabaseConfig(BaseModel):
    """Create a new, or alter an existing, database."""

    operation: Literal["create_or_alter_database"] = Field(
        "create_or_alter_database",
        json_schema_extra={
            "const": "create_or_alter_database", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Create or Alter Database",
        },
        title="Create or Alter Database",
    )
    name: str = Field(
        ..., title="Database", description="Name of the database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    kind: Optional[str] = Field(
        None, title="Kind", description="Database type, permanent (default) or transient",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the database")
    data_retention_time_in_days: Optional[str] = Field(
        None, title="Data Retention (days)", description="Time Travel retention time in days")
    default_ddl_collation: Optional[str] = Field(
        None, title="Default DDL Collation", description="Default collation for schemas and tables")
    log_level: Optional[str] = Field(
        None, title="Log Level", description="Severity level of ingested messages")
    max_data_extension_time_in_days: Optional[str] = Field(
        None, title="Max Data Extension (days)", description="Max days Snowflake can extend data retention")
    suspend_task_after_num_failures: Optional[str] = Field(
        None, title="Suspend Task After Failures", description="Consecutive failed task runs before suspend")
    trace_level: Optional[str] = Field(
        None, title="Trace Level", description="How trace events are ingested into the event table")
    user_task_managed_initial_warehouse_size: Optional[str] = Field(
        None, title="Task Initial Warehouse Size",
        description="Compute size for the first run of a serverless task")
    user_task_timeout_ms: Optional[str] = Field(
        None, title="User Task Timeout (ms)", description="Time limit for a single task run in ms")
    serverless_task_min_statement_size: Optional[str] = Field(
        None, title="Serverless Task Min Size", description="Minimum allowed warehouse size for serverless task")
    serverless_task_max_statement_size: Optional[str] = Field(
        None, title="Serverless Task Max Size", description="Maximum allowed warehouse size for serverless task")


class SnowflakeUndropDatabaseConfig(BaseModel):
    """Undrop a database."""

    operation: Literal["undrop_database"] = Field(
        "undrop_database",
        json_schema_extra={
            "const": "undrop_database", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Undrop Database",
        },
        title="Undrop Database",
    )
    name: str = Field(..., title="Database", description="The database to undrop")


class SnowflakeEnableDatabaseReplicationConfig(BaseModel):
    """Enable replication for a database."""

    operation: Literal["enable_database_replication"] = Field(
        "enable_database_replication",
        json_schema_extra={
            "const": "enable_database_replication", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Enable Database Replication",
        },
        title="Enable Database Replication",
    )
    name: str = Field(
        ..., title="Database", description="The primary database to enable replication for",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    accounts: str = Field(
        ..., title="Accounts", description="Comma-separated account identifiers to replicate to")
    ignore_edition_check: Optional[str] = Field(
        None, title="Ignore Edition Check", description="Allow replicating to accounts on lower editions",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeDisableDatabaseReplicationConfig(BaseModel):
    """Disable replication for a database."""

    operation: Literal["disable_database_replication"] = Field(
        "disable_database_replication",
        json_schema_extra={
            "const": "disable_database_replication", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Disable Database Replication",
        },
        title="Disable Database Replication",
    )
    name: str = Field(
        ..., title="Database", description="The primary database to disable replication for",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    accounts: Optional[str] = Field(
        None, title="Accounts", description="Comma-separated account identifiers (optional)")


class SnowflakeRefreshDatabaseReplicationConfig(BaseModel):
    """Refresh a secondary database from its primary."""

    operation: Literal["refresh_database_replication"] = Field(
        "refresh_database_replication",
        json_schema_extra={
            "const": "refresh_database_replication", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Refresh Database Replication",
        },
        title="Refresh Database Replication",
    )
    name: str = Field(
        ..., title="Database", description="The secondary database to refresh",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )


class SnowflakeEnableDatabaseFailoverConfig(BaseModel):
    """Enable failover for a database."""

    operation: Literal["enable_database_failover"] = Field(
        "enable_database_failover",
        json_schema_extra={
            "const": "enable_database_failover", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Enable Database Failover",
        },
        title="Enable Database Failover",
    )
    name: str = Field(
        ..., title="Database", description="The primary database to enable failover for",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    accounts: str = Field(
        ..., title="Accounts", description="Comma-separated account identifiers eligible for failover")


class SnowflakeDisableDatabaseFailoverConfig(BaseModel):
    """Disable failover for a database."""

    operation: Literal["disable_database_failover"] = Field(
        "disable_database_failover",
        json_schema_extra={
            "const": "disable_database_failover", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Disable Database Failover",
        },
        title="Disable Database Failover",
    )
    name: str = Field(
        ..., title="Database", description="The primary database to disable failover for",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    accounts: Optional[str] = Field(
        None, title="Accounts", description="Comma-separated account identifiers (optional)")


class SnowflakePrimaryDatabaseFailoverConfig(BaseModel):
    """Promote a secondary database to primary."""

    operation: Literal["primary_database_failover"] = Field(
        "primary_database_failover",
        json_schema_extra={
            "const": "primary_database_failover", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Set Primary Database (Failover)",
        },
        title="Set Primary Database (Failover)",
    )
    name: str = Field(
        ..., title="Database", description="The secondary database to promote to primary",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )


class SnowflakeSetTagsConfig(BaseModel):
    """Set a tag on a database."""

    operation: Literal["set_tags"] = Field(
        "set_tags",
        json_schema_extra={
            "const": "set_tags", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Set Database Tags",
        },
        title="Set Database Tags",
    )
    name: str = Field(
        ..., title="Database", description="The database to tag",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the database is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsConfig(BaseModel):
    """Unset tags from a database."""

    operation: Literal["unset_tags"] = Field(
        "unset_tags",
        json_schema_extra={
            "const": "unset_tags", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Unset Database Tags",
        },
        title="Unset Database Tags",
    )
    name: str = Field(
        ..., title="Database", description="The database to untag",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    tag_name: str = Field(..., title="Tag Name(s)", description="Comma-separated tag names to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the database is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsConfig(BaseModel):
    """Get the tag assignments for a database."""

    operation: Literal["get_tags"] = Field(
        "get_tags",
        json_schema_extra={
            "const": "get_tags", "ui:hidden": True, "x-category": "Databases",
            "x-is-trigger": False, "x-display-name": "Get Database Tags",
        },
        title="Get Database Tags",
    )
    name: str = Field(
        ..., title="Database", description="The database whose tags to fetch",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_accounts(value):
    return [a.strip() for a in value.split(",") if a.strip()] if value else None


async def _create_database_from_share(node, c, account, token):
    params = {"createMode": c.create_mode, "share": c.share}
    body = {"name": c.name}
    return await node._request(account, token, "POST", "/databases:from-share",
                               params=params, json_body=body, action_name="create_database_from_share")


async def _create_database_from_share_deprecated(node, c, account, token):
    ep = f"/databases/{c.name}:from_share"
    params = {"createMode": c.create_mode, "share": c.share}
    return await node._request(account, token, "POST", ep, params=params,
                               action_name="create_database_from_share_deprecated")


async def _clone_database(node, c, account, token):
    ep = f"/databases/{c.name}:clone"
    params = {"createMode": c.create_mode, "kind": c.kind}
    body = {"name": c.new_name, "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="clone_database")


async def _create_or_alter_database(node, c, account, token):
    ep = f"/databases/{c.name}"
    body = {
        "name": c.name, "kind": c.kind, "comment": c.comment,
        "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
        "default_ddl_collation": c.default_ddl_collation,
        "log_level": c.log_level,
        "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
        "suspend_task_after_num_failures": _sf_int(c.suspend_task_after_num_failures),
        "trace_level": c.trace_level,
        "user_task_managed_initial_warehouse_size": c.user_task_managed_initial_warehouse_size,
        "user_task_timeout_ms": _sf_int(c.user_task_timeout_ms),
        "serverless_task_min_statement_size": c.serverless_task_min_statement_size,
        "serverless_task_max_statement_size": c.serverless_task_max_statement_size,
    }
    return await node._request(account, token, "PUT", ep, json_body=body,
                               action_name="create_or_alter_database")


async def _undrop_database(node, c, account, token):
    ep = f"/databases/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_database")


async def _enable_database_replication(node, c, account, token):
    ep = f"/databases/{c.name}/replication:enable"
    params = {"ignore_edition_check": _sf_bool(c.ignore_edition_check)}
    body = {"accounts": _sf_accounts(c.accounts)}
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="enable_database_replication")


async def _disable_database_replication(node, c, account, token):
    ep = f"/databases/{c.name}/replication:disable"
    accounts = _sf_accounts(c.accounts)
    body = {"accounts": accounts} if accounts else None
    return await node._request(account, token, "POST", ep, json_body=body,
                               action_name="disable_database_replication")


async def _refresh_database_replication(node, c, account, token):
    ep = f"/databases/{c.name}/replication:refresh"
    return await node._request(account, token, "POST", ep, action_name="refresh_database_replication")


async def _enable_database_failover(node, c, account, token):
    ep = f"/databases/{c.name}/failover:enable"
    body = {"accounts": _sf_accounts(c.accounts)}
    return await node._request(account, token, "POST", ep, json_body=body,
                               action_name="enable_database_failover")


async def _disable_database_failover(node, c, account, token):
    ep = f"/databases/{c.name}/failover:disable"
    accounts = _sf_accounts(c.accounts)
    body = {"accounts": accounts} if accounts else None
    return await node._request(account, token, "POST", ep, json_body=body,
                               action_name="disable_database_failover")


async def _primary_database_failover(node, c, account, token):
    ep = f"/databases/{c.name}/failover:primary"
    return await node._request(account, token, "POST", ep, action_name="primary_database_failover")


async def _set_tags(node, c, account, token):
    ep = f"/databases/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="set_tags")


async def _unset_tags(node, c, account, token):
    ep = f"/databases/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": n.strip()} for n in c.tag_name.split(",") if n.strip()]
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="unset_tags")


async def _get_tags(node, c, account, token):
    ep = f"/databases/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeCreateDatabaseFromShareConfig,
    SnowflakeCreateDatabaseFromShareDeprecatedConfig,
    SnowflakeCloneDatabaseConfig,
    SnowflakeCreateOrAlterDatabaseConfig,
    SnowflakeUndropDatabaseConfig,
    SnowflakeEnableDatabaseReplicationConfig,
    SnowflakeDisableDatabaseReplicationConfig,
    SnowflakeRefreshDatabaseReplicationConfig,
    SnowflakeEnableDatabaseFailoverConfig,
    SnowflakeDisableDatabaseFailoverConfig,
    SnowflakePrimaryDatabaseFailoverConfig,
    SnowflakeSetTagsConfig,
    SnowflakeUnsetTagsConfig,
    SnowflakeGetTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "create_database_from_share": _create_database_from_share,
    "create_database_from_share_deprecated": _create_database_from_share_deprecated,
    "clone_database": _clone_database,
    "create_or_alter_database": _create_or_alter_database,
    "undrop_database": _undrop_database,
    "enable_database_replication": _enable_database_replication,
    "disable_database_replication": _disable_database_replication,
    "refresh_database_replication": _refresh_database_replication,
    "enable_database_failover": _enable_database_failover,
    "disable_database_failover": _disable_database_failover,
    "primary_database_failover": _primary_database_failover,
    "set_tags": _set_tags,
    "unset_tags": _unset_tags,
    "get_tags": _get_tags,
})


# ---- database_role.py ----
class SnowflakeListDatabaseRolesConfig(BaseModel):
    """List database roles in a database."""

    operation: Literal["list_database_roles"] = Field(
        "list_database_roles",
        json_schema_extra={
            "const": "list_database_roles", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "List Database Roles",
        },
        title="List Database Roles",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateDatabaseRoleConfig(BaseModel):
    """Create a database role in a database."""

    operation: Literal["create_database_role"] = Field(
        "create_database_role",
        json_schema_extra={
            "const": "create_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Create Database Role",
        },
        title="Create Database Role",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Name", description="Name of the database role to create")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the database role")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the database role already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeDeleteDatabaseRoleConfig(BaseModel):
    """Drop a database role."""

    operation: Literal["delete_database_role"] = Field(
        "delete_database_role",
        json_schema_extra={
            "const": "delete_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Delete Database Role",
        },
        title="Delete Database Role",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the database role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneDatabaseRoleConfig(BaseModel):
    """Clone a database role into a (possibly different) database."""

    operation: Literal["clone_database_role"] = Field(
        "clone_database_role",
        json_schema_extra={
            "const": "clone_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Clone Database Role",
        },
        title="Clone Database Role",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to clone")
    target_name: str = Field(..., title="New Name", description="Name of the cloned database role")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeListGrantsConfig(BaseModel):
    """List all grants to a database role."""

    operation: Literal["list_grants_database_role"] = Field(
        "list_grants_database_role",
        json_schema_extra={
            "const": "list_grants_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "List Grants",
        },
        title="List Grants",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role whose grants to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeGrantPrivilegesConfig(BaseModel):
    """Grant privileges to a database role."""

    operation: Literal["grant_privileges_database_role"] = Field(
        "grant_privileges_database_role",
        json_schema_extra={
            "const": "grant_privileges_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Grant Privileges",
        },
        title="Grant Privileges",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to grant to")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be granted (e.g. TABLE, SCHEMA)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Allow the recipient role to grant these privileges to others",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database of the securable, if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema of the securable, if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service of the securable, if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable, if applicable")
    containing_scope_database: Optional[str] = Field(None, title="Scope Database", description="Database of the containing scope, if applicable")
    containing_scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema of the containing scope, if applicable")


class SnowflakeRevokeGrantsConfig(BaseModel):
    """Revoke grants from a database role."""

    operation: Literal["revoke_grants_database_role"] = Field(
        "revoke_grants_database_role",
        json_schema_extra={
            "const": "revoke_grants_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Revoke Grants",
        },
        title="Revoke Grants",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to revoke from")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be revoked (e.g. TABLE, SCHEMA)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to revoke")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Revoke only the grant option, leaving the privilege",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    mode: Optional[str] = Field(
        None, title="Mode", description="Drop behavior for dependent privileges",
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database of the securable, if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema of the securable, if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service of the securable, if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable, if applicable")
    containing_scope_database: Optional[str] = Field(None, title="Scope Database", description="Database of the containing scope, if applicable")
    containing_scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema of the containing scope, if applicable")


class SnowflakeListFutureGrantsConfig(BaseModel):
    """List all future grants to a database role."""

    operation: Literal["list_future_grants_database_role"] = Field(
        "list_future_grants_database_role",
        json_schema_extra={
            "const": "list_future_grants_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "List Future Grants",
        },
        title="List Future Grants",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role whose future grants to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeGrantFuturePrivilegesConfig(BaseModel):
    """Grant future privileges to a database role."""

    operation: Literal["grant_future_privileges_database_role"] = Field(
        "grant_future_privileges_database_role",
        json_schema_extra={
            "const": "grant_future_privileges_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Grant Future Privileges",
        },
        title="Grant Future Privileges",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to grant to")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be granted (e.g. TABLE)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Allow the recipient role to grant these privileges to others",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database of the securable, if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema of the securable, if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service of the securable, if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable, if applicable")
    containing_scope_database: Optional[str] = Field(None, title="Scope Database", description="Database of the containing scope, if applicable")
    containing_scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema of the containing scope, if applicable")


class SnowflakeRevokeFutureGrantsConfig(BaseModel):
    """Revoke future grants from a database role."""

    operation: Literal["revoke_future_grants_database_role"] = Field(
        "revoke_future_grants_database_role",
        json_schema_extra={
            "const": "revoke_future_grants_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Revoke Future Grants",
        },
        title="Revoke Future Grants",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to revoke from")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be revoked (e.g. TABLE)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to revoke")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Revoke only the grant option, leaving the privilege",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    mode: Optional[str] = Field(
        None, title="Mode", description="Drop behavior for dependent privileges",
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database of the securable, if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema of the securable, if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service of the securable, if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable, if applicable")
    containing_scope_database: Optional[str] = Field(None, title="Scope Database", description="Database of the containing scope, if applicable")
    containing_scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema of the containing scope, if applicable")


class SnowflakeSetTagsDatabaseRoleConfig(BaseModel):
    """Set a tag on a database role."""

    operation: Literal["set_tags_database_role"] = Field(
        "set_tags_database_role",
        json_schema_extra={
            "const": "set_tags_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Set Tags on Database Role",
        },
        title="Set Tags on Database Role",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign for the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the database role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsDatabaseRoleConfig(BaseModel):
    """Unset a tag from a database role."""

    operation: Literal["unset_tags_database_role"] = Field(
        "unset_tags_database_role",
        json_schema_extra={
            "const": "unset_tags_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Unset Tags on Database Role",
        },
        title="Unset Tags on Database Role",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the database role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsDatabaseRoleConfig(BaseModel):
    """Get the tag assignments for a database role (requires an active warehouse)."""

    operation: Literal["get_tags_database_role"] = Field(
        "get_tags_database_role",
        json_schema_extra={
            "const": "get_tags_database_role", "ui:hidden": True, "x-category": "Database Roles",
            "x-is-trigger": False, "x-display-name": "Get Tags on Database Role",
        },
        title="Get Tags on Database Role",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Database Role", description="The database role whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _build_grant_body(c):
    securable = {
        "database": c.securable_database, "schema": c.securable_schema,
        "service": c.securable_service, "name": c.securable_name,
    }
    securable = {k: v for k, v in securable.items() if v is not None}
    scope = {"database": c.containing_scope_database, "schema": c.containing_scope_schema}
    scope = {k: v for k, v in scope.items() if v is not None}
    body = {
        "securable_type": c.securable_type,
        "privileges": [p.strip() for p in c.privileges.split(",") if p.strip()] if c.privileges else None,
        "grant_option": _sf_bool(c.grant_option),
    }
    if securable:
        body["securable"] = securable
    if scope:
        body["containing_scope"] = scope
    return body


async def _list_database_roles(node, c, account, token):
    base = f"/databases/{c.database}/database-roles"
    params = {"showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_database_roles")


async def _create_database_role(node, c, account, token):
    base = f"/databases/{c.database}/database-roles"
    body = {"name": c.name, "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_database_role")


async def _delete_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_database_role")


async def _clone_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}:clone"
    params = {"createMode": c.create_mode, "targetDatabase": c.target_database}
    body = {"name": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_database_role")


async def _list_grants_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/grants"
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", ep, params=params, action_name="list_grants_database_role")


async def _grant_privileges_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/grants"
    body = _build_grant_body(c)
    return await node._request(account, token, "POST", ep, json_body=body, action_name="grant_privileges_database_role")


async def _revoke_grants_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/grants:revoke"
    params = {"mode": c.mode} if c.mode else None
    body = _build_grant_body(c)
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="revoke_grants_database_role")


async def _list_future_grants_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/future-grants"
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", ep, params=params, action_name="list_future_grants_database_role")


async def _grant_future_privileges_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/future-grants"
    body = _build_grant_body(c)
    return await node._request(account, token, "POST", ep, json_body=body, action_name="grant_future_privileges_database_role")


async def _revoke_future_grants_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}/future-grants:revoke"
    params = {"mode": c.mode} if c.mode else None
    body = _build_grant_body(c)
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="revoke_future_grants_database_role")


async def _set_tags_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_database_role")


async def _unset_tags_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_database_role")


async def _get_tags_database_role(node, c, account, token):
    ep = f"/databases/{c.database}/database-roles/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_database_role")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListDatabaseRolesConfig,
    SnowflakeCreateDatabaseRoleConfig,
    SnowflakeDeleteDatabaseRoleConfig,
    SnowflakeCloneDatabaseRoleConfig,
    SnowflakeListGrantsConfig,
    SnowflakeGrantPrivilegesConfig,
    SnowflakeRevokeGrantsConfig,
    SnowflakeListFutureGrantsConfig,
    SnowflakeGrantFuturePrivilegesConfig,
    SnowflakeRevokeFutureGrantsConfig,
    SnowflakeSetTagsDatabaseRoleConfig,
    SnowflakeUnsetTagsDatabaseRoleConfig,
    SnowflakeGetTagsDatabaseRoleConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_database_roles": _list_database_roles,
    "create_database_role": _create_database_role,
    "delete_database_role": _delete_database_role,
    "clone_database_role": _clone_database_role,
    "list_grants_database_role": _list_grants_database_role,
    "grant_privileges_database_role": _grant_privileges_database_role,
    "revoke_grants_database_role": _revoke_grants_database_role,
    "list_future_grants_database_role": _list_future_grants_database_role,
    "grant_future_privileges_database_role": _grant_future_privileges_database_role,
    "revoke_future_grants_database_role": _revoke_future_grants_database_role,
    "set_tags_database_role": _set_tags_database_role,
    "unset_tags_database_role": _unset_tags_database_role,
    "get_tags_database_role": _get_tags_database_role,
})


# ---- dynamic_table.py ----
class SnowflakeListDynamicTablesConfig(BaseModel):
    """List dynamic tables under a database and schema."""

    operation: Literal["list_dynamic_tables"] = Field(
        "list_dynamic_tables",
        json_schema_extra={
            "const": "list_dynamic_tables", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "List Dynamic Tables",
        },
        title="List Dynamic Tables",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")
    deep: Optional[str] = Field(
        None, title="Deep", description="Include dependency information of the dynamic table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateDynamicTableConfig(BaseModel):
    """Create a dynamic table in a schema."""

    operation: Literal["create_dynamic_table"] = Field(
        "create_dynamic_table",
        json_schema_extra={
            "const": "create_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Create Dynamic Table",
        },
        title="Create Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the dynamic table to create")
    warehouse: str = Field(..., title="Warehouse", description="Warehouse that refreshes the dynamic table")
    query: str = Field(..., title="Query", description="Query whose results the dynamic table should contain")
    target_lag: str = Field(..., title="Target Lag", description="Refresh lag: a duration like '1 hour', '60 seconds', '2 days', or 'DOWNSTREAM'")
    columns: Optional[str] = Field(
        None, title="Columns",
        description='JSON array of column definitions, e.g. [{"name": "id"}, {"name": "email", "comment": "..."}]',
    )
    kind: Optional[str] = Field(
        None, title="Kind", description="Dynamic table type",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT"], "x-enum-searchable": True},
    )
    refresh_mode: Optional[str] = Field(
        None, title="Refresh Mode", description="Refresh type for the dynamic table",
        json_schema_extra={"enum": ["AUTO", "FULL", "INCREMENTAL"], "x-enum-searchable": True},
    )
    initialize: Optional[str] = Field(
        None, title="Initialize", description="Behavior of the initial refresh",
        json_schema_extra={"enum": ["ON_CREATE", "ON_SCHEDULE"], "x-enum-searchable": True},
    )
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention Days", description="Time Travel retention period in days")
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension Days", description="Maximum Time Travel extension period in days")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the dynamic table")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the dynamic table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchDynamicTableConfig(BaseModel):
    """Fetch a single dynamic table's definition."""

    operation: Literal["fetch_dynamic_table"] = Field(
        "fetch_dynamic_table",
        json_schema_extra={
            "const": "fetch_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Fetch Dynamic Table",
        },
        title="Fetch Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to fetch")


class SnowflakeDeleteDynamicTableConfig(BaseModel):
    """Drop a dynamic table."""

    operation: Literal["delete_dynamic_table"] = Field(
        "delete_dynamic_table",
        json_schema_extra={
            "const": "delete_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Delete Dynamic Table",
        },
        title="Delete Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneDynamicTableConfig(BaseModel):
    """Clone a dynamic table into a (possibly different) schema."""

    operation: Literal["clone_dynamic_table"] = Field(
        "clone_dynamic_table",
        json_schema_extra={
            "const": "clone_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Clone Dynamic Table",
        },
        title="Clone Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to clone")
    target_name: str = Field(..., title="New Name", description="Name of the newly created dynamic table")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    target_lag: Optional[str] = Field(None, title="Target Lag", description="Target lag for the clone (e.g. '1 hour')")
    warehouse: Optional[str] = Field(None, title="Warehouse", description="Warehouse for the cloned dynamic table")
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeUndropDynamicTableConfig(BaseModel):
    """Undrop a previously dropped dynamic table."""

    operation: Literal["undrop_dynamic_table"] = Field(
        "undrop_dynamic_table",
        json_schema_extra={
            "const": "undrop_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Undrop Dynamic Table",
        },
        title="Undrop Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to undrop")


class SnowflakeSuspendDynamicTableConfig(BaseModel):
    """Suspend refreshes on a dynamic table."""

    operation: Literal["suspend_dynamic_table"] = Field(
        "suspend_dynamic_table",
        json_schema_extra={
            "const": "suspend_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Suspend Dynamic Table",
        },
        title="Suspend Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to suspend")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeResumeDynamicTableConfig(BaseModel):
    """Resume refreshes on a dynamic table."""

    operation: Literal["resume_dynamic_table"] = Field(
        "resume_dynamic_table",
        json_schema_extra={
            "const": "resume_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Resume Dynamic Table",
        },
        title="Resume Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to resume")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRefreshDynamicTableConfig(BaseModel):
    """Manually refresh a dynamic table."""

    operation: Literal["refresh_dynamic_table"] = Field(
        "refresh_dynamic_table",
        json_schema_extra={
            "const": "refresh_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Refresh Dynamic Table",
        },
        title="Refresh Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to refresh")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSuspendReclusterDynamicTableConfig(BaseModel):
    """Suspend recluster of a dynamic table."""

    operation: Literal["suspend_recluster_dynamic_table"] = Field(
        "suspend_recluster_dynamic_table",
        json_schema_extra={
            "const": "suspend_recluster_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Suspend Recluster Dynamic Table",
        },
        title="Suspend Recluster Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to suspend reclustering on")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeResumeReclusterDynamicTableConfig(BaseModel):
    """Resume recluster of a dynamic table."""

    operation: Literal["resume_recluster_dynamic_table"] = Field(
        "resume_recluster_dynamic_table",
        json_schema_extra={
            "const": "resume_recluster_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Resume Recluster Dynamic Table",
        },
        title="Resume Recluster Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to resume reclustering on")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSwapWithDynamicTableConfig(BaseModel):
    """Swap a dynamic table with another dynamic table."""

    operation: Literal["swap_with_dynamic_table"] = Field(
        "swap_with_dynamic_table",
        json_schema_extra={
            "const": "swap_with_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Swap With Dynamic Table",
        },
        title="Swap With Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Dynamic Table", description="The source dynamic table")
    target_name: str = Field(..., title="Target Name", description="The target dynamic table to swap with")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsDynamicTableConfig(BaseModel):
    """Set a tag on a dynamic table."""

    operation: Literal["set_tags_dynamic_table"] = Field(
        "set_tags_dynamic_table",
        json_schema_extra={
            "const": "set_tags_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Set Tags on Dynamic Table",
        },
        title="Set Tags on Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value of the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsDynamicTableConfig(BaseModel):
    """Unset a tag from a dynamic table."""

    operation: Literal["unset_tags_dynamic_table"] = Field(
        "unset_tags_dynamic_table",
        json_schema_extra={
            "const": "unset_tags_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Unset Tags on Dynamic Table",
        },
        title="Unset Tags on Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the dynamic table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsDynamicTableConfig(BaseModel):
    """Get the tag assignments for a dynamic table."""

    operation: Literal["get_tags_dynamic_table"] = Field(
        "get_tags_dynamic_table",
        json_schema_extra={
            "const": "get_tags_dynamic_table", "ui:hidden": True, "x-category": "Dynamic Tables",
            "x-is-trigger": False, "x-display-name": "Get Tags on Dynamic Table",
        },
        title="Get Tags on Dynamic Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Dynamic Table", description="The dynamic table to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_dynamic_tables(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit,
              "fromName": c.from_name, "deep": _sf_bool(c.deep)}
    return await node._request(account, token, "GET", base, params=params, action_name="list_dynamic_tables")


async def _create_dynamic_table(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables"
    cluster_by = [s.strip() for s in c.cluster_by.split(",")] if c.cluster_by else None
    body = {"name": c.name, "warehouse": c.warehouse, "query": c.query, "target_lag": _sf_target_lag(c.target_lag),
            "columns": _sf_json(c.columns) if c.columns else None,
            "kind": c.kind, "refresh_mode": c.refresh_mode, "initialize": c.initialize,
            "cluster_by": cluster_by, "comment": c.comment,
            "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
            "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days)}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_dynamic_table")


async def _fetch_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_dynamic_table")


async def _delete_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_dynamic_table")


async def _clone_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:clone"
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants),
              "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    body = {"name": c.target_name, "target_lag": _sf_target_lag(c.target_lag), "warehouse": c.warehouse}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_dynamic_table")


async def _undrop_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_dynamic_table")


async def _suspend_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:suspend"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_dynamic_table")


async def _resume_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:resume"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_dynamic_table")


async def _refresh_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:refresh"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="refresh_dynamic_table")


async def _suspend_recluster_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:suspend-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_recluster_dynamic_table")


async def _resume_recluster_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:resume-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_recluster_dynamic_table")


async def _swap_with_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:swap-with"
    params = {"ifExists": _sf_bool(c.if_exists), "targetName": c.target_name,
              "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    return await node._request(account, token, "POST", ep, params=params, action_name="swap_with_dynamic_table")


async def _set_tags_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_dynamic_table")


async def _unset_tags_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_dynamic_table")


async def _get_tags_dynamic_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/dynamic-tables/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_dynamic_table")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListDynamicTablesConfig,
    SnowflakeCreateDynamicTableConfig,
    SnowflakeFetchDynamicTableConfig,
    SnowflakeDeleteDynamicTableConfig,
    SnowflakeCloneDynamicTableConfig,
    SnowflakeUndropDynamicTableConfig,
    SnowflakeSuspendDynamicTableConfig,
    SnowflakeResumeDynamicTableConfig,
    SnowflakeRefreshDynamicTableConfig,
    SnowflakeSuspendReclusterDynamicTableConfig,
    SnowflakeResumeReclusterDynamicTableConfig,
    SnowflakeSwapWithDynamicTableConfig,
    SnowflakeSetTagsDynamicTableConfig,
    SnowflakeUnsetTagsDynamicTableConfig,
    SnowflakeGetTagsDynamicTableConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_dynamic_tables": _list_dynamic_tables,
    "create_dynamic_table": _create_dynamic_table,
    "fetch_dynamic_table": _fetch_dynamic_table,
    "delete_dynamic_table": _delete_dynamic_table,
    "clone_dynamic_table": _clone_dynamic_table,
    "undrop_dynamic_table": _undrop_dynamic_table,
    "suspend_dynamic_table": _suspend_dynamic_table,
    "resume_dynamic_table": _resume_dynamic_table,
    "refresh_dynamic_table": _refresh_dynamic_table,
    "suspend_recluster_dynamic_table": _suspend_recluster_dynamic_table,
    "resume_recluster_dynamic_table": _resume_recluster_dynamic_table,
    "swap_with_dynamic_table": _swap_with_dynamic_table,
    "set_tags_dynamic_table": _set_tags_dynamic_table,
    "unset_tags_dynamic_table": _unset_tags_dynamic_table,
    "get_tags_dynamic_table": _get_tags_dynamic_table,
})


# ---- event_table.py ----
class SnowflakeListEventTablesConfig(BaseModel):
    """List event tables in a schema."""

    operation: Literal["list_event_tables"] = Field(
        "list_event_tables",
        json_schema_extra={
            "const": "list_event_tables", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "List Event Tables",
        },
        title="List Event Tables",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateEventTableConfig(BaseModel):
    """Create an event table in a schema."""

    operation: Literal["create_event_table"] = Field(
        "create_event_table",
        json_schema_extra={
            "const": "create_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Create Event Table",
        },
        title="Create Event Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the event table to create")
    cluster_by: Optional[str] = Field(
        None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    data_retention_time_in_days: Optional[str] = Field(
        None, title="Data Retention Time (Days)",
        description="Number of days to retain the old version of deleted/updated data")
    max_data_extension_time_in_days: Optional[str] = Field(
        None, title="Max Data Extension Time (Days)",
        description="Maximum number of days to extend data retention to prevent a stream becoming stale")
    change_tracking: Optional[str] = Field(
        None, title="Change Tracking", description="Enable change tracking (streams / CHANGES)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    default_ddl_collation: Optional[str] = Field(
        None, title="Default DDL Collation",
        description="Collation used for all new columns created by DDL statements")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the event table")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the event table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source when replacing",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchEventTableConfig(BaseModel):
    """Fetch a single event table's definition."""

    operation: Literal["fetch_event_table"] = Field(
        "fetch_event_table",
        json_schema_extra={
            "const": "fetch_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Fetch Event Table",
        },
        title="Fetch Event Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to fetch")


class SnowflakeDeleteEventTableConfig(BaseModel):
    """Drop an event table."""

    operation: Literal["delete_event_table"] = Field(
        "delete_event_table",
        json_schema_extra={
            "const": "delete_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Delete Event Table",
        },
        title="Delete Event Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the event table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRenameEventTableConfig(BaseModel):
    """Rename an event table to a new identifier."""

    operation: Literal["rename_event_table"] = Field(
        "rename_event_table",
        json_schema_extra={
            "const": "rename_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Rename Event Table",
        },
        title="Rename Event Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed event table")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the event table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsEventTableConfig(BaseModel):
    """Set a tag on an event table."""

    operation: Literal["set_tags_event_table"] = Field(
        "set_tags_event_table",
        json_schema_extra={
            "const": "set_tags_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Set Event Table Tags",
        },
        title="Set Event Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the event table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsEventTableConfig(BaseModel):
    """Unset a tag from an event table."""

    operation: Literal["unset_tags_event_table"] = Field(
        "unset_tags_event_table",
        json_schema_extra={
            "const": "unset_tags_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Unset Event Table Tags",
        },
        title="Unset Event Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the event table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsEventTableConfig(BaseModel):
    """Get the tag assignments for an event table (requires an active warehouse)."""

    operation: Literal["get_tags_event_table"] = Field(
        "get_tags_event_table",
        json_schema_extra={
            "const": "get_tags_event_table", "ui:hidden": True, "x-category": "Event Tables",
            "x-is-trigger": False, "x-display-name": "Get Event Table Tags",
        },
        title="Get Event Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Event Table", description="The event table to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_event_tables(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_event_tables")


async def _create_event_table(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables"
    cluster_by = [s.strip() for s in c.cluster_by.split(",")] if c.cluster_by else None
    body = {"name": c.name,
            "cluster_by": cluster_by,
            "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
            "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
            "change_tracking": _sf_bool(c.change_tracking),
            "default_ddl_collation": c.default_ddl_collation,
            "comment": c.comment}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_event_table")


async def _fetch_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_event_table")


async def _delete_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_event_table")


async def _rename_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_event_table")


async def _set_tags_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_event_table")


async def _unset_tags_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_event_table")


async def _get_tags_event_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/event-tables/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_event_table")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListEventTablesConfig,
    SnowflakeCreateEventTableConfig,
    SnowflakeFetchEventTableConfig,
    SnowflakeDeleteEventTableConfig,
    SnowflakeRenameEventTableConfig,
    SnowflakeSetTagsEventTableConfig,
    SnowflakeUnsetTagsEventTableConfig,
    SnowflakeGetTagsEventTableConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_event_tables": _list_event_tables,
    "create_event_table": _create_event_table,
    "fetch_event_table": _fetch_event_table,
    "delete_event_table": _delete_event_table,
    "rename_event_table": _rename_event_table,
    "set_tags_event_table": _set_tags_event_table,
    "unset_tags_event_table": _unset_tags_event_table,
    "get_tags_event_table": _get_tags_event_table,
})


# ---- external_volume.py ----
class SnowflakeListExternalVolumesConfig(BaseModel):
    """List external volumes in the account."""

    operation: Literal["list_external_volumes"] = Field(
        "list_external_volumes",
        json_schema_extra={
            "const": "list_external_volumes", "ui:hidden": True, "x-category": "External Volumes",
            "x-is-trigger": False, "x-display-name": "List External Volumes",
        },
        title="List External Volumes",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateExternalVolumeConfig(BaseModel):
    """Create an external volume."""

    operation: Literal["create_external_volume"] = Field(
        "create_external_volume",
        json_schema_extra={
            "const": "create_external_volume", "ui:hidden": True, "x-category": "External Volumes",
            "x-is-trigger": False, "x-display-name": "Create External Volume",
        },
        title="Create External Volume",
    )
    name: str = Field(..., title="Name", description="Name of the external volume to create")
    storage_locations: str = Field(
        ..., title="Storage Locations",
        description="JSON array of named cloud storage locations (e.g. [{\"name\": \"...\", \"storage_provider\": \"S3\", ...}])",
    )
    allow_writes: Optional[str] = Field(
        None, title="Allow Writes", description="Whether write operations are allowed for the external volume",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the external volume")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the external volume already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchExternalVolumeConfig(BaseModel):
    """Fetch a single external volume's definition."""

    operation: Literal["fetch_external_volume"] = Field(
        "fetch_external_volume",
        json_schema_extra={
            "const": "fetch_external_volume", "ui:hidden": True, "x-category": "External Volumes",
            "x-is-trigger": False, "x-display-name": "Fetch External Volume",
        },
        title="Fetch External Volume",
    )
    name: str = Field(..., title="External Volume", description="The external volume to fetch")


class SnowflakeDeleteExternalVolumeConfig(BaseModel):
    """Drop an external volume."""

    operation: Literal["delete_external_volume"] = Field(
        "delete_external_volume",
        json_schema_extra={
            "const": "delete_external_volume", "ui:hidden": True, "x-category": "External Volumes",
            "x-is-trigger": False, "x-display-name": "Delete External Volume",
        },
        title="Delete External Volume",
    )
    name: str = Field(..., title="External Volume", description="The external volume to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the external volume is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropExternalVolumeConfig(BaseModel):
    """Restore the most recently dropped external volume with a given name."""

    operation: Literal["undrop_external_volume"] = Field(
        "undrop_external_volume",
        json_schema_extra={
            "const": "undrop_external_volume", "ui:hidden": True, "x-category": "External Volumes",
            "x-is-trigger": False, "x-display-name": "Undrop External Volume",
        },
        title="Undrop External Volume",
    )
    name: str = Field(..., title="External Volume", description="The external volume to undrop")


async def _list_external_volumes(node, c, account, token):
    params = {"like": c.like}
    return await node._request(account, token, "GET", "/external-volumes", params=params, action_name="list_external_volumes")


async def _create_external_volume(node, c, account, token):
    body = {"name": c.name, "storage_locations": c.storage_locations,
            "allow_writes": _sf_bool(c.allow_writes), "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/external-volumes", params=params, json_body=body, action_name="create_external_volume")


async def _fetch_external_volume(node, c, account, token):
    ep = f"/external-volumes/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_external_volume")


async def _delete_external_volume(node, c, account, token):
    ep = f"/external-volumes/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_external_volume")


async def _undrop_external_volume(node, c, account, token):
    ep = f"/external-volumes/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_external_volume")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListExternalVolumesConfig,
    SnowflakeCreateExternalVolumeConfig,
    SnowflakeFetchExternalVolumeConfig,
    SnowflakeDeleteExternalVolumeConfig,
    SnowflakeUndropExternalVolumeConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_external_volumes": _list_external_volumes,
    "create_external_volume": _create_external_volume,
    "fetch_external_volume": _fetch_external_volume,
    "delete_external_volume": _delete_external_volume,
    "undrop_external_volume": _undrop_external_volume,
})


# ---- function.py ----
class SnowflakeListFunctionsConfig(BaseModel):
    """List user functions in a schema."""

    operation: Literal["list_functions"] = Field(
        "list_functions",
        json_schema_extra={
            "const": "list_functions", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "List Functions",
        },
        title="List Functions",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateFunctionConfig(BaseModel):
    """Create a function in a schema."""

    operation: Literal["create_function"] = Field(
        "create_function",
        json_schema_extra={
            "const": "create_function", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Create Function",
        },
        title="Create Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the function to create")
    arguments: Optional[str] = Field(
        None, title="Arguments",
        description="JSON array of function arguments, e.g. [{\"name\":\"x\",\"datatype\":\"TEXT\"}]",
    )
    returns: Optional[str] = Field(None, title="Returns", description="Return value type (e.g. TEXT)")
    max_batch_rows: Optional[str] = Field(None, title="Max Batch Rows", description="Max rows for batch operation")
    language: Optional[str] = Field(None, title="Language", description="Function's language")
    body: Optional[str] = Field(None, title="Body", description="Function's body")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the function already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchFunctionConfig(BaseModel):
    """Fetch a single function's definition."""

    operation: Literal["fetch_function"] = Field(
        "fetch_function",
        json_schema_extra={
            "const": "fetch_function", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Fetch Function",
        },
        title="Fetch Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="Function name with arguments, e.g. my_func(TEXT)")


class SnowflakeDeleteFunctionConfig(BaseModel):
    """Drop a function."""

    operation: Literal["delete_function"] = Field(
        "delete_function",
        json_schema_extra={
            "const": "delete_function", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Delete Function",
        },
        title="Delete Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="Function name with arguments, e.g. my_func(TEXT)")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the function is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeExecuteFunctionConfig(BaseModel):
    """Execute a function."""

    operation: Literal["execute_function"] = Field(
        "execute_function",
        json_schema_extra={
            "const": "execute_function", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Execute Function",
        },
        title="Execute Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="The function to execute")


class SnowflakeSetFunctionTagsConfig(BaseModel):
    """Set tags on a function."""

    operation: Literal["set_function_tags"] = Field(
        "set_function_tags",
        json_schema_extra={
            "const": "set_function_tags", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Set Function Tags",
        },
        title="Set Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="Function name with arguments, e.g. my_func(TEXT)")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value of the tag to assign")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the function is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetFunctionTagsConfig(BaseModel):
    """Unset tags from a function."""

    operation: Literal["unset_function_tags"] = Field(
        "unset_function_tags",
        json_schema_extra={
            "const": "unset_function_tags", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Unset Function Tags",
        },
        title="Unset Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="Function name with arguments, e.g. my_func(TEXT)")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the function is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetFunctionTagsConfig(BaseModel):
    """Get the tag assignments for a function."""

    operation: Literal["get_function_tags"] = Field(
        "get_function_tags",
        json_schema_extra={
            "const": "get_function_tags", "ui:hidden": True, "x-category": "Functions",
            "x-is-trigger": False, "x-display-name": "Get Function Tags",
        },
        title="Get Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Function", description="Function name with arguments, e.g. my_func(TEXT)")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_functions(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/functions"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_functions")


async def _create_function(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/functions"
    body = {"name": c.name, "arguments": c.arguments, "returns": c.returns,
            "max_batch_rows": _sf_int(c.max_batch_rows), "language": c.language, "body": c.body}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_function")


async def _fetch_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_function")


async def _delete_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_function")


async def _execute_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}:execute"
    return await node._request(account, token, "POST", ep, action_name="execute_function")


async def _set_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_function_tags")


async def _unset_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_function_tags")


async def _get_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/functions/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_function_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListFunctionsConfig,
    SnowflakeCreateFunctionConfig,
    SnowflakeFetchFunctionConfig,
    SnowflakeDeleteFunctionConfig,
    SnowflakeExecuteFunctionConfig,
    SnowflakeSetFunctionTagsConfig,
    SnowflakeUnsetFunctionTagsConfig,
    SnowflakeGetFunctionTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_functions": _list_functions,
    "create_function": _create_function,
    "fetch_function": _fetch_function,
    "delete_function": _delete_function,
    "execute_function": _execute_function,
    "set_function_tags": _set_function_tags,
    "unset_function_tags": _unset_function_tags,
    "get_function_tags": _get_function_tags,
})


# ---- grant.py ----
class SnowflakeGrantPrivilegeConfig(BaseModel):
    """Grant the specified privilege(s) on the named securable to the named grantee."""

    operation: Literal["grant_privilege"] = Field(
        "grant_privilege",
        json_schema_extra={
            "const": "grant_privilege", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Grant Privilege",
        },
        title="Grant Privilege",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    securable_type: str = Field(..., title="Securable Type", description="Type of resource being secured by a privilege")
    securable_name: str = Field(..., title="Securable Name", description="Name of resource being secured by a privilege")
    privileges: str = Field(..., title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Can the grantee pass this privilege down?",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGrantGroupPrivilegeConfig(BaseModel):
    """Grant privilege(s) on all/future securables of a type in a scope to the named grantee."""

    operation: Literal["grant_group_privilege"] = Field(
        "grant_group_privilege",
        json_schema_extra={
            "const": "grant_group_privilege", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Grant Group Privilege",
        },
        title="Grant Group Privilege",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    bulk_grant_type: str = Field(
        ..., title="Bulk Grant Type", description="Whether this group privilege applies to ALL or FUTURE resources",
        json_schema_extra={"enum": ["all", "future"], "x-enum-searchable": True},
    )
    securable_type_plural: str = Field(..., title="Securable Type (Plural)", description='Plural securable type, e.g. "schemas" or "tables"')
    scope_type: str = Field(
        ..., title="Scope Type", description="Type of resource that is the scope of the ALL/FUTURE privilege",
        json_schema_extra={"enum": ["database", "schema"], "x-enum-searchable": True},
    )
    scope_name: str = Field(..., title="Scope Name", description="Name of resource that is the scope of the ALL/FUTURE privilege")
    privileges: str = Field(..., title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Can the grantee pass this privilege down?",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRevokePrivilegeConfig(BaseModel):
    """Revoke the specified privilege on the named securable from the named grantee."""

    operation: Literal["revoke_privilege"] = Field(
        "revoke_privilege",
        json_schema_extra={
            "const": "revoke_privilege", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Revoke Privilege",
        },
        title="Revoke Privilege",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    securable_type: str = Field(..., title="Securable Type", description="Type of resource being secured by a privilege")
    securable_name: str = Field(..., title="Securable Name", description="Name of resource being secured by a privilege")
    privilege: str = Field(..., title="Privilege", description="The privilege to revoke")
    delete_mode: Optional[str] = Field(
        None, title="Delete Mode", description='"restrict" or "cascade" (recursively revoke re-grants)',
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeRevokePrivilegeGrantOptionConfig(BaseModel):
    """Revoke the grant option for the specified privilege on the named securable."""

    operation: Literal["revoke_privilege_grant_option"] = Field(
        "revoke_privilege_grant_option",
        json_schema_extra={
            "const": "revoke_privilege_grant_option", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Revoke Privilege Grant Option",
        },
        title="Revoke Privilege Grant Option",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    securable_type: str = Field(..., title="Securable Type", description="Type of resource being secured by a privilege")
    securable_name: str = Field(..., title="Securable Name", description="Name of resource being secured by a privilege")
    privilege: str = Field(..., title="Privilege", description="The privilege whose grant option to revoke")
    delete_mode: Optional[str] = Field(
        None, title="Delete Mode", description='"restrict" or "cascade" (recursively revoke re-grants)',
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeRevokeGroupPrivilegeConfig(BaseModel):
    """Revoke a privilege on all/future securables in the given scope from the named grantee."""

    operation: Literal["revoke_group_privilege"] = Field(
        "revoke_group_privilege",
        json_schema_extra={
            "const": "revoke_group_privilege", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Revoke Group Privilege",
        },
        title="Revoke Group Privilege",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    bulk_grant_type: str = Field(
        ..., title="Bulk Grant Type", description="Whether this group privilege applies to ALL or FUTURE resources",
        json_schema_extra={"enum": ["all", "future"], "x-enum-searchable": True},
    )
    securable_type_plural: str = Field(..., title="Securable Type (Plural)", description='Plural securable type, e.g. "schemas" or "tables"')
    scope_type: str = Field(
        ..., title="Scope Type", description="Type of resource that is the scope of the ALL/FUTURE privilege",
        json_schema_extra={"enum": ["database", "schema"], "x-enum-searchable": True},
    )
    scope_name: str = Field(..., title="Scope Name", description="Name of resource that is the scope of the ALL/FUTURE privilege")
    privilege: str = Field(..., title="Privilege", description="The privilege to revoke")
    delete_mode: Optional[str] = Field(
        None, title="Delete Mode", description='"restrict" or "cascade" (recursively revoke re-grants)',
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeRevokeGroupPrivilegeGrantOptionConfig(BaseModel):
    """Revoke the grant option for a privilege on all/future securables in the given scope."""

    operation: Literal["revoke_group_privilege_grant_option"] = Field(
        "revoke_group_privilege_grant_option",
        json_schema_extra={
            "const": "revoke_group_privilege_grant_option", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "Revoke Group Privilege Grant Option",
        },
        title="Revoke Group Privilege Grant Option",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    bulk_grant_type: str = Field(
        ..., title="Bulk Grant Type", description="Whether this group privilege applies to ALL or FUTURE resources",
        json_schema_extra={"enum": ["all", "future"], "x-enum-searchable": True},
    )
    securable_type_plural: str = Field(..., title="Securable Type (Plural)", description='Plural securable type, e.g. "schemas" or "tables"')
    scope_type: str = Field(
        ..., title="Scope Type", description="Type of resource that is the scope of the ALL/FUTURE privilege",
        json_schema_extra={"enum": ["database", "schema"], "x-enum-searchable": True},
    )
    scope_name: str = Field(..., title="Scope Name", description="Name of resource that is the scope of the ALL/FUTURE privilege")
    privilege: str = Field(..., title="Privilege", description="The privilege whose grant option to revoke")
    delete_mode: Optional[str] = Field(
        None, title="Delete Mode", description='"restrict" or "cascade" (recursively revoke re-grants)',
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeListGrantsToConfig(BaseModel):
    """List the roles and privileges granted to the specified grantee."""

    operation: Literal["list_grants_to"] = Field(
        "list_grants_to",
        json_schema_extra={
            "const": "list_grants_to", "ui:hidden": True, "x-category": "Grants",
            "x-is-trigger": False, "x-display-name": "List Grants To",
        },
        title="List Grants To",
    )
    grantee_type: str = Field(
        ..., title="Grantee Type", description="Type of resource that is the privilege grantee",
        json_schema_extra={"enum": ["user", "role", "application-role", "database-role", "share"], "x-enum-searchable": True},
    )
    grantee_name: str = Field(..., title="Grantee Name", description="Name of the privilege grantee")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


def _sf_privileges(raw):
    return [p.strip() for p in raw.split(",") if p.strip()] if raw else None


async def _grant_privilege(node, c, account, token):
    ep = f"/grants/{c.grantee_type}/{c.grantee_name}/{c.securable_type}/{c.securable_name}/privileges"
    body = {"privileges": _sf_privileges(c.privileges), "grant_option": _sf_bool(c.grant_option)}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="grant_privilege")


async def _grant_group_privilege(node, c, account, token):
    ep = (f"/grants/{c.grantee_type}/{c.grantee_name}/{c.bulk_grant_type}/{c.securable_type_plural}"
          f"/{c.scope_type}/{c.scope_name}/privileges")
    body = {"privileges": _sf_privileges(c.privileges), "grant_option": _sf_bool(c.grant_option)}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="grant_group_privilege")


async def _revoke_privilege(node, c, account, token):
    ep = f"/grants/{c.grantee_type}/{c.grantee_name}/{c.securable_type}/{c.securable_name}/privileges/{c.privilege}"
    params = {"deleteMode": c.delete_mode}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="revoke_privilege")


async def _revoke_privilege_grant_option(node, c, account, token):
    ep = (f"/grants/{c.grantee_type}/{c.grantee_name}/{c.securable_type}/{c.securable_name}"
          f"/privileges/{c.privilege}/grant-option")
    params = {"deleteMode": c.delete_mode}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="revoke_privilege_grant_option")


async def _revoke_group_privilege(node, c, account, token):
    ep = (f"/grants/{c.grantee_type}/{c.grantee_name}/{c.bulk_grant_type}/{c.securable_type_plural}"
          f"/{c.scope_type}/{c.scope_name}/privileges/{c.privilege}")
    params = {"deleteMode": c.delete_mode}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="revoke_group_privilege")


async def _revoke_group_privilege_grant_option(node, c, account, token):
    ep = (f"/grants/{c.grantee_type}/{c.grantee_name}/{c.bulk_grant_type}/{c.securable_type_plural}"
          f"/{c.scope_type}/{c.scope_name}/privileges/{c.privilege}/grant-option")
    params = {"deleteMode": c.delete_mode}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="revoke_group_privilege_grant_option")


async def _list_grants_to(node, c, account, token):
    ep = f"/grants/{c.grantee_type}/{c.grantee_name}"
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", ep, params=params, action_name="list_grants_to")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeGrantPrivilegeConfig,
    SnowflakeGrantGroupPrivilegeConfig,
    SnowflakeRevokePrivilegeConfig,
    SnowflakeRevokePrivilegeGrantOptionConfig,
    SnowflakeRevokeGroupPrivilegeConfig,
    SnowflakeRevokeGroupPrivilegeGrantOptionConfig,
    SnowflakeListGrantsToConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "grant_privilege": _grant_privilege,
    "grant_group_privilege": _grant_group_privilege,
    "revoke_privilege": _revoke_privilege,
    "revoke_privilege_grant_option": _revoke_privilege_grant_option,
    "revoke_group_privilege": _revoke_group_privilege,
    "revoke_group_privilege_grant_option": _revoke_group_privilege_grant_option,
    "list_grants_to": _list_grants_to,
})


# ---- iceberg_table.py ----
class SnowflakeListIcebergTablesConfig(BaseModel):
    """List iceberg tables in a schema."""

    operation: Literal["list_iceberg_tables"] = Field(
        "list_iceberg_tables",
        json_schema_extra={
            "const": "list_iceberg_tables", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "List Iceberg Tables",
        },
        title="List Iceberg Tables",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")
    deep: Optional[str] = Field(
        None, title="Deep", description="Include dependency information of the table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableConfig(BaseModel):
    """Create a Snowflake-managed iceberg table."""

    operation: Literal["create_snowflake_managed_iceberg_table"] = Field(
        "create_snowflake_managed_iceberg_table",
        json_schema_extra={
            "const": "create_snowflake_managed_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table",
        },
        title="Create Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume for Iceberg metadata and data files")
    base_location: Optional[str] = Field(None, title="Base Location", description="Directory where Snowflake writes data and metadata files")
    catalog: Optional[str] = Field(None, title="Catalog", description="Name of the catalog integration to use")
    catalog_sync: Optional[str] = Field(None, title="Catalog Sync", description="Name of the catalog integration to sync this table")
    catalog_table_name: Optional[str] = Field(None, title="Catalog Table Name", description="Name of the table as recognized by the catalog")
    catalog_namespace: Optional[str] = Field(None, title="Catalog Namespace", description="Catalog namespace for the table")
    metadata_file_path: Optional[str] = Field(None, title="Metadata File Path", description="Relative path of the Iceberg metadata file for column definitions")
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    change_tracking: Optional[str] = Field(
        None, title="Change Tracking", description="Enable change tracking (streams and CHANGES)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    replace_invalid_characters: Optional[str] = Field(
        None, title="Replace Invalid Characters", description="Replace invalid characters in column names",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention (days)", description="Days to retain old versions of deleted/updated data")
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension (days)", description="Max days to extend data retention to keep streams fresh")
    storage_serialization_policy: Optional[str] = Field(
        None, title="Storage Serialization Policy", description="Storage serialization policy for the managed table",
        json_schema_extra={"enum": ["COMPATIBLE", "OPTIMIZED"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the replaced table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableAsSelectConfig(BaseModel):
    """Create a Snowflake-managed iceberg table from a SELECT query."""

    operation: Literal["create_snowflake_managed_iceberg_table_as_select"] = Field(
        "create_snowflake_managed_iceberg_table_as_select",
        json_schema_extra={
            "const": "create_snowflake_managed_iceberg_table_as_select", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table as Select",
        },
        title="Create Iceberg Table as Select",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    query: str = Field(..., title="Query", description="The SQL SELECT query used to populate the table")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    base_location: Optional[str] = Field(None, title="Base Location", description="Directory where Snowflake writes data and metadata files")
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the replaced table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableFromAWSGlueCatalogConfig(BaseModel):
    """Create an unmanaged iceberg table from an AWS Glue catalog."""

    operation: Literal["create_unmanaged_iceberg_table_from_aws_glue_catalog"] = Field(
        "create_unmanaged_iceberg_table_from_aws_glue_catalog",
        json_schema_extra={
            "const": "create_unmanaged_iceberg_table_from_aws_glue_catalog", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table from AWS Glue",
        },
        title="Create Iceberg Table from AWS Glue",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    catalog_table_name: str = Field(..., title="Catalog Table Name", description="Table name as recognized by the AWS Glue Data Catalog")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    catalog_namespace: Optional[str] = Field(None, title="Catalog Namespace", description="Catalog namespace for the table")
    catalog: Optional[str] = Field(None, title="Catalog", description="Name of the catalog integration to use")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    replace_invalid_characters: Optional[str] = Field(
        None, title="Replace Invalid Characters", description="Replace invalid characters in column names",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_refresh: Optional[str] = Field(
        None, title="Auto Refresh", description="Automatically refresh the table metadata",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableFromDeltaConfig(BaseModel):
    """Create an unmanaged iceberg table from Delta files."""

    operation: Literal["create_unmanaged_iceberg_table_from_delta"] = Field(
        "create_unmanaged_iceberg_table_from_delta",
        json_schema_extra={
            "const": "create_unmanaged_iceberg_table_from_delta", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table from Delta",
        },
        title="Create Iceberg Table from Delta",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    base_location: str = Field(..., title="Base Location", description="Relative path from the external volume to the Delta table files")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    catalog: Optional[str] = Field(None, title="Catalog", description="Name of the catalog integration to use")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    replace_invalid_characters: Optional[str] = Field(
        None, title="Replace Invalid Characters", description="Replace invalid characters in column names",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableFromIcebergFilesConfig(BaseModel):
    """Create an unmanaged iceberg table from Iceberg files."""

    operation: Literal["create_unmanaged_iceberg_table_from_iceberg_files"] = Field(
        "create_unmanaged_iceberg_table_from_iceberg_files",
        json_schema_extra={
            "const": "create_unmanaged_iceberg_table_from_iceberg_files", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table from Iceberg Files",
        },
        title="Create Iceberg Table from Iceberg Files",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    metadata_file_path: str = Field(..., title="Metadata File Path", description="Relative path of the Iceberg metadata file for column definitions")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    catalog: Optional[str] = Field(None, title="Catalog", description="Name of the catalog integration to use")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    replace_invalid_characters: Optional[str] = Field(
        None, title="Replace Invalid Characters", description="Replace invalid characters in column names",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableFromIcebergRestConfig(BaseModel):
    """Create an unmanaged iceberg table from an Iceberg REST catalog."""

    operation: Literal["create_unmanaged_iceberg_table_from_iceberg_rest"] = Field(
        "create_unmanaged_iceberg_table_from_iceberg_rest",
        json_schema_extra={
            "const": "create_unmanaged_iceberg_table_from_iceberg_rest", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table from Iceberg REST",
        },
        title="Create Iceberg Table from Iceberg REST",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the iceberg table to create")
    catalog_table_name: str = Field(..., title="Catalog Table Name", description="Table name as recognized by the catalog")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    catalog_namespace: Optional[str] = Field(None, title="Catalog Namespace", description="Catalog namespace for the table")
    catalog: Optional[str] = Field(None, title="Catalog", description="Name of the catalog integration to use")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    replace_invalid_characters: Optional[str] = Field(
        None, title="Replace Invalid Characters", description="Replace invalid characters in column names",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_refresh: Optional[str] = Field(
        None, title="Auto Refresh", description="Automatically refresh the table metadata",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchIcebergTableConfig(BaseModel):
    """Describe a single iceberg table."""

    operation: Literal["fetch_iceberg_table"] = Field(
        "fetch_iceberg_table",
        json_schema_extra={
            "const": "fetch_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Fetch Iceberg Table",
        },
        title="Fetch Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to describe")


class SnowflakeDropIcebergTableConfig(BaseModel):
    """Drop an iceberg table."""

    operation: Literal["drop_iceberg_table"] = Field(
        "drop_iceberg_table",
        json_schema_extra={
            "const": "drop_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Drop Iceberg Table",
        },
        title="Drop Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    type: Optional[str] = Field(
        None, title="Type", description="Whether to drop with dependent foreign keys",
        json_schema_extra={"enum": ["CASCADE", "RESTRICT"], "x-enum-searchable": True},
    )


class SnowflakeResumeReclusterIcebergTableConfig(BaseModel):
    """Resume reclustering of an iceberg table."""

    operation: Literal["resume_recluster_iceberg_table"] = Field(
        "resume_recluster_iceberg_table",
        json_schema_extra={
            "const": "resume_recluster_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Resume Recluster Iceberg Table",
        },
        title="Resume Recluster Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to resume reclustering")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSuspendReclusterIcebergTableConfig(BaseModel):
    """Suspend reclustering of an iceberg table."""

    operation: Literal["suspend_recluster_iceberg_table"] = Field(
        "suspend_recluster_iceberg_table",
        json_schema_extra={
            "const": "suspend_recluster_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Suspend Recluster Iceberg Table",
        },
        title="Suspend Recluster Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to suspend reclustering")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRefreshIcebergTableConfig(BaseModel):
    """Refresh metadata for an externally-cataloged iceberg table."""

    operation: Literal["refresh_iceberg_table"] = Field(
        "refresh_iceberg_table",
        json_schema_extra={
            "const": "refresh_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Refresh Iceberg Table",
        },
        title="Refresh Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to refresh")
    metadata_file_relative_path: Optional[str] = Field(None, title="Metadata File Relative Path", description="Metadata file path for a table created from Iceberg files in object storage")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeConvertToManagedIcebergTableConfig(BaseModel):
    """Convert an unmanaged iceberg table to a Snowflake-managed one."""

    operation: Literal["convert_to_managed_iceberg_table"] = Field(
        "convert_to_managed_iceberg_table",
        json_schema_extra={
            "const": "convert_to_managed_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Convert to Managed Iceberg Table",
        },
        title="Convert to Managed Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to convert")
    base_location: Optional[str] = Field(None, title="Base Location", description="Directory where Snowflake writes data and metadata files")
    storage_serialization_policy: Optional[str] = Field(
        None, title="Storage Serialization Policy", description="Storage serialization policy for the table",
        json_schema_extra={"enum": ["COMPATIBLE", "OPTIMIZED"], "x-enum-searchable": True},
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropIcebergTableConfig(BaseModel):
    """Undrop a previously dropped iceberg table."""

    operation: Literal["undrop_iceberg_table"] = Field(
        "undrop_iceberg_table",
        json_schema_extra={
            "const": "undrop_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Undrop Iceberg Table",
        },
        title="Undrop Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to undrop")


class SnowflakeCloneIcebergTableConfig(BaseModel):
    """Clone a Snowflake-managed iceberg table."""

    operation: Literal["clone_snowflake_managed_iceberg_table"] = Field(
        "clone_snowflake_managed_iceberg_table",
        json_schema_extra={
            "const": "clone_snowflake_managed_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Clone Iceberg Table",
        },
        title="Clone Iceberg Table",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Iceberg Table", description="The source iceberg table to clone")
    target_name: str = Field(..., title="New Name", description="Name for the newly cloned table")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateIcebergTableLikeConfig(BaseModel):
    """Create a new iceberg table with the same column definitions as an existing one."""

    operation: Literal["create_snowflake_managed_iceberg_table_like"] = Field(
        "create_snowflake_managed_iceberg_table_like",
        json_schema_extra={
            "const": "create_snowflake_managed_iceberg_table_like", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Create Iceberg Table Like",
        },
        title="Create Iceberg Table Like",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Source Iceberg Table", description="The existing table to base the new table on")
    target_name: str = Field(..., title="New Name", description="Name for the newly created table")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    external_volume: Optional[str] = Field(None, title="External Volume", description="External volume to use for the table")
    base_location: Optional[str] = Field(None, title="Base Location", description="Directory where Snowflake writes data and metadata files")
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsIcebergTableConfig(BaseModel):
    """Set a tag on an iceberg table."""

    operation: Literal["set_tags_iceberg_table"] = Field(
        "set_tags_iceberg_table",
        json_schema_extra={
            "const": "set_tags_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Set Iceberg Table Tags",
        },
        title="Set Iceberg Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsIcebergTableConfig(BaseModel):
    """Unset a tag from an iceberg table."""

    operation: Literal["unset_tags_iceberg_table"] = Field(
        "unset_tags_iceberg_table",
        json_schema_extra={
            "const": "unset_tags_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Unset Iceberg Table Tags",
        },
        title="Unset Iceberg Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsIcebergTableConfig(BaseModel):
    """Get the tag assignments for an iceberg table."""

    operation: Literal["get_tags_iceberg_table"] = Field(
        "get_tags_iceberg_table",
        json_schema_extra={
            "const": "get_tags_iceberg_table", "ui:hidden": True, "x-category": "Iceberg Tables",
            "x-is-trigger": False, "x-display-name": "Get Iceberg Table Tags",
        },
        title="Get Iceberg Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Iceberg Table", description="The iceberg table whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_iceberg_tables(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit,
              "fromName": c.from_name, "deep": _sf_bool(c.deep)}
    return await node._request(account, token, "GET", base, params=params, action_name="list_iceberg_tables")


async def _create_snowflake_managed_iceberg_table(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables"
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    body = {"name": c.name, "external_volume": c.external_volume, "base_location": c.base_location,
            "catalog": c.catalog, "catalog_sync": c.catalog_sync, "catalog_table_name": c.catalog_table_name,
            "catalog_namespace": c.catalog_namespace, "metadata_file_path": c.metadata_file_path,
            "cluster_by": _sf_cluster_by(c.cluster_by),
            "comment": c.comment, "change_tracking": _sf_bool(c.change_tracking),
            "replace_invalid_characters": _sf_bool(c.replace_invalid_characters),
            "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
            "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
            "storage_serialization_policy": c.storage_serialization_policy}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_snowflake_managed_iceberg_table")


async def _create_snowflake_managed_iceberg_table_as_select(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables:as-select"
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants), "query": c.query}
    body = {"name": c.name, "external_volume": c.external_volume,
            "base_location": c.base_location, "cluster_by": _sf_cluster_by(c.cluster_by),
            "comment": c.comment}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_snowflake_managed_iceberg_table_as_select")


async def _create_unmanaged_iceberg_table_from_aws_glue_catalog(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables:from-aws-glue-catalog"
    params = {"createMode": c.create_mode}
    body = {"name": c.name, "external_volume": c.external_volume, "catalog_table_name": c.catalog_table_name,
            "catalog_namespace": c.catalog_namespace, "catalog": c.catalog, "comment": c.comment,
            "replace_invalid_characters": _sf_bool(c.replace_invalid_characters),
            "auto_refresh": _sf_bool(c.auto_refresh)}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_unmanaged_iceberg_table_from_aws_glue_catalog")


async def _create_unmanaged_iceberg_table_from_delta(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables:from-delta"
    params = {"createMode": c.create_mode}
    body = {"name": c.name, "external_volume": c.external_volume, "base_location": c.base_location,
            "catalog": c.catalog, "comment": c.comment,
            "replace_invalid_characters": _sf_bool(c.replace_invalid_characters)}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_unmanaged_iceberg_table_from_delta")


async def _create_unmanaged_iceberg_table_from_iceberg_files(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables:from-iceberg-files"
    params = {"createMode": c.create_mode}
    body = {"name": c.name, "external_volume": c.external_volume, "metadata_file_path": c.metadata_file_path,
            "catalog": c.catalog, "comment": c.comment,
            "replace_invalid_characters": _sf_bool(c.replace_invalid_characters)}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_unmanaged_iceberg_table_from_iceberg_files")


async def _create_unmanaged_iceberg_table_from_iceberg_rest(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables:from-iceberg-rest"
    params = {"createMode": c.create_mode}
    body = {"name": c.name, "external_volume": c.external_volume, "catalog_table_name": c.catalog_table_name,
            "catalog_namespace": c.catalog_namespace, "catalog": c.catalog, "comment": c.comment,
            "replace_invalid_characters": _sf_bool(c.replace_invalid_characters),
            "auto_refresh": _sf_bool(c.auto_refresh)}
    return await node._request(account, token, "POST", base, params=params, json_body=body,
                               action_name="create_unmanaged_iceberg_table_from_iceberg_rest")


async def _fetch_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_iceberg_table")


async def _drop_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists), "type": c.type}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="drop_iceberg_table")


async def _resume_recluster_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:resume-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_recluster_iceberg_table")


async def _suspend_recluster_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:suspend-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_recluster_iceberg_table")


async def _refresh_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:refresh"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"metadata_file_relative_path": c.metadata_file_relative_path}
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="refresh_iceberg_table")


async def _convert_to_managed_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:convert-to-managed"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"base_location": c.base_location, "storage_serialization_policy": c.storage_serialization_policy}
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="convert_to_managed_iceberg_table")


async def _undrop_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_iceberg_table")


async def _clone_snowflake_managed_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:clone"
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants),
              "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    body = {"name": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="clone_snowflake_managed_iceberg_table")


async def _create_snowflake_managed_iceberg_table_like(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:create-like"
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants),
              "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    body = {"name": c.target_name, "external_volume": c.external_volume,
            "base_location": c.base_location, "cluster_by": _sf_cluster_by(c.cluster_by),
            "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="create_snowflake_managed_iceberg_table_like")


async def _set_tags_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="set_tags_iceberg_table")


async def _unset_tags_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body,
                               action_name="unset_tags_iceberg_table")


async def _get_tags_iceberg_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/iceberg-tables/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_iceberg_table")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListIcebergTablesConfig,
    SnowflakeCreateIcebergTableConfig,
    SnowflakeCreateIcebergTableAsSelectConfig,
    SnowflakeCreateIcebergTableFromAWSGlueCatalogConfig,
    SnowflakeCreateIcebergTableFromDeltaConfig,
    SnowflakeCreateIcebergTableFromIcebergFilesConfig,
    SnowflakeCreateIcebergTableFromIcebergRestConfig,
    SnowflakeFetchIcebergTableConfig,
    SnowflakeDropIcebergTableConfig,
    SnowflakeResumeReclusterIcebergTableConfig,
    SnowflakeSuspendReclusterIcebergTableConfig,
    SnowflakeRefreshIcebergTableConfig,
    SnowflakeConvertToManagedIcebergTableConfig,
    SnowflakeUndropIcebergTableConfig,
    SnowflakeCloneIcebergTableConfig,
    SnowflakeCreateIcebergTableLikeConfig,
    SnowflakeSetTagsIcebergTableConfig,
    SnowflakeUnsetTagsIcebergTableConfig,
    SnowflakeGetTagsIcebergTableConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_iceberg_tables": _list_iceberg_tables,
    "create_snowflake_managed_iceberg_table": _create_snowflake_managed_iceberg_table,
    "create_snowflake_managed_iceberg_table_as_select": _create_snowflake_managed_iceberg_table_as_select,
    "create_unmanaged_iceberg_table_from_aws_glue_catalog": _create_unmanaged_iceberg_table_from_aws_glue_catalog,
    "create_unmanaged_iceberg_table_from_delta": _create_unmanaged_iceberg_table_from_delta,
    "create_unmanaged_iceberg_table_from_iceberg_files": _create_unmanaged_iceberg_table_from_iceberg_files,
    "create_unmanaged_iceberg_table_from_iceberg_rest": _create_unmanaged_iceberg_table_from_iceberg_rest,
    "fetch_iceberg_table": _fetch_iceberg_table,
    "drop_iceberg_table": _drop_iceberg_table,
    "resume_recluster_iceberg_table": _resume_recluster_iceberg_table,
    "suspend_recluster_iceberg_table": _suspend_recluster_iceberg_table,
    "refresh_iceberg_table": _refresh_iceberg_table,
    "convert_to_managed_iceberg_table": _convert_to_managed_iceberg_table,
    "undrop_iceberg_table": _undrop_iceberg_table,
    "clone_snowflake_managed_iceberg_table": _clone_snowflake_managed_iceberg_table,
    "create_snowflake_managed_iceberg_table_like": _create_snowflake_managed_iceberg_table_like,
    "set_tags_iceberg_table": _set_tags_iceberg_table,
    "unset_tags_iceberg_table": _unset_tags_iceberg_table,
    "get_tags_iceberg_table": _get_tags_iceberg_table,
})


# ---- image_repository.py ----
class SnowflakeListImageRepositoriesConfig(BaseModel):
    """List image repositories in a schema."""

    operation: Literal["list_image_repositories"] = Field(
        "list_image_repositories",
        json_schema_extra={
            "const": "list_image_repositories", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "List Image Repositories",
        },
        title="List Image Repositories",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateImageRepositoryConfig(BaseModel):
    """Create an image repository in a schema."""

    operation: Literal["create_image_repository"] = Field(
        "create_image_repository",
        json_schema_extra={
            "const": "create_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Create Image Repository",
        },
        title="Create Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the image repository to create")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the image repository already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchImageRepositoryConfig(BaseModel):
    """Fetch a single image repository's definition."""

    operation: Literal["fetch_image_repository"] = Field(
        "fetch_image_repository",
        json_schema_extra={
            "const": "fetch_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Fetch Image Repository",
        },
        title="Fetch Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository to fetch")


class SnowflakeDeleteImageRepositoryConfig(BaseModel):
    """Drop an image repository."""

    operation: Literal["delete_image_repository"] = Field(
        "delete_image_repository",
        json_schema_extra={
            "const": "delete_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Delete Image Repository",
        },
        title="Delete Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the image repository is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeListImagesInRepositoryConfig(BaseModel):
    """List the images stored in an image repository."""

    operation: Literal["list_images_in_repository"] = Field(
        "list_images_in_repository",
        json_schema_extra={
            "const": "list_images_in_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "List Images in Repository",
        },
        title="List Images in Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository whose images to list")


class SnowflakeSetTagsImageRepositoryConfig(BaseModel):
    """Set a tag on an image repository."""

    operation: Literal["set_tags_image_repository"] = Field(
        "set_tags_image_repository",
        json_schema_extra={
            "const": "set_tags_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Set Tags on Image Repository",
        },
        title="Set Tags on Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the image repository is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsImageRepositoryConfig(BaseModel):
    """Unset a tag from an image repository."""

    operation: Literal["unset_tags_image_repository"] = Field(
        "unset_tags_image_repository",
        json_schema_extra={
            "const": "unset_tags_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Unset Tags from Image Repository",
        },
        title="Unset Tags from Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the image repository is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsImageRepositoryConfig(BaseModel):
    """Get the tag assignments for an image repository."""

    operation: Literal["get_tags_image_repository"] = Field(
        "get_tags_image_repository",
        json_schema_extra={
            "const": "get_tags_image_repository", "ui:hidden": True, "x-category": "Image Repositories",
            "x-is-trigger": False, "x-display-name": "Get Tags on Image Repository",
        },
        title="Get Tags on Image Repository",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Image Repository", description="The image repository whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_image_repositories(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_image_repositories")


async def _create_image_repository(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories"
    body = {"name": c.name}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_image_repository")


async def _fetch_image_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_image_repository")


async def _delete_image_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_image_repository")


async def _list_images_in_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}/images"
    return await node._request(account, token, "GET", ep, action_name="list_images_in_repository")


async def _set_tags_image_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_image_repository")


async def _unset_tags_image_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_image_repository")


async def _get_tags_image_repository(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/image-repositories/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_image_repository")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListImageRepositoriesConfig,
    SnowflakeCreateImageRepositoryConfig,
    SnowflakeFetchImageRepositoryConfig,
    SnowflakeDeleteImageRepositoryConfig,
    SnowflakeListImagesInRepositoryConfig,
    SnowflakeSetTagsImageRepositoryConfig,
    SnowflakeUnsetTagsImageRepositoryConfig,
    SnowflakeGetTagsImageRepositoryConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_image_repositories": _list_image_repositories,
    "create_image_repository": _create_image_repository,
    "fetch_image_repository": _fetch_image_repository,
    "delete_image_repository": _delete_image_repository,
    "list_images_in_repository": _list_images_in_repository,
    "set_tags_image_repository": _set_tags_image_repository,
    "unset_tags_image_repository": _unset_tags_image_repository,
    "get_tags_image_repository": _get_tags_image_repository,
})


# ---- managed_account.py ----
class SnowflakeListManagedAccountsConfig(BaseModel):
    """List the accessible managed accounts."""

    operation: Literal["list_managed_accounts"] = Field(
        "list_managed_accounts",
        json_schema_extra={
            "const": "list_managed_accounts", "ui:hidden": True, "x-category": "Managed Accounts",
            "x-is-trigger": False, "x-display-name": "List Managed Accounts",
        },
        title="List Managed Accounts",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateManagedAccountConfig(BaseModel):
    """Create a managed account (reader account)."""

    operation: Literal["create_managed_account"] = Field(
        "create_managed_account",
        json_schema_extra={
            "const": "create_managed_account", "ui:hidden": True, "x-category": "Managed Accounts",
            "x-is-trigger": False, "x-display-name": "Create Managed Account",
        },
        title="Create Managed Account",
    )
    name: str = Field(..., title="Name", description="Name of the managed account to create")
    admin_name: str = Field(..., title="Admin Name", description="Name of the account administrator")
    admin_password: str = Field(..., title="Admin Password", description="Password for the account administrator")
    account_type: Optional[str] = Field(
        "READER", title="Account Type", description="Type of the account",
        json_schema_extra={"enum": ["READER"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the account")


class SnowflakeDeleteManagedAccountConfig(BaseModel):
    """Delete a managed account, including all objects created in it."""

    operation: Literal["delete_managed_account"] = Field(
        "delete_managed_account",
        json_schema_extra={
            "const": "delete_managed_account", "ui:hidden": True, "x-category": "Managed Accounts",
            "x-is-trigger": False, "x-display-name": "Delete Managed Account",
        },
        title="Delete Managed Account",
    )
    name: str = Field(..., title="Managed Account", description="The managed account to delete")


async def _list_managed_accounts(node, c, account, token):
    params = {"like": c.like}
    return await node._request(account, token, "GET", "/managed-accounts", params=params, action_name="list_managed_accounts")


async def _create_managed_account(node, c, account, token):
    body = {"name": c.name, "admin_name": c.admin_name, "admin_password": c.admin_password,
            "account_type": c.account_type, "comment": c.comment}
    return await node._request(account, token, "POST", "/managed-accounts", json_body=body, action_name="create_managed_account")


async def _delete_managed_account(node, c, account, token):
    ep = f"/managed-accounts/{c.name}"
    return await node._request(account, token, "DELETE", ep, action_name="delete_managed_account")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListManagedAccountsConfig,
    SnowflakeCreateManagedAccountConfig,
    SnowflakeDeleteManagedAccountConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_managed_accounts": _list_managed_accounts,
    "create_managed_account": _create_managed_account,
    "delete_managed_account": _delete_managed_account,
})


# ---- network_policy.py ----
class SnowflakeListNetworkPoliciesConfig(BaseModel):
    """List network policies in the account."""

    operation: Literal["list_network_policies"] = Field(
        "list_network_policies",
        json_schema_extra={
            "const": "list_network_policies", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "List Network Policies",
        },
        title="List Network Policies",
    )


class SnowflakeCreateNetworkPolicyConfig(BaseModel):
    """Create a network policy."""

    operation: Literal["create_network_policy"] = Field(
        "create_network_policy",
        json_schema_extra={
            "const": "create_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Create Network Policy",
        },
        title="Create Network Policy",
    )
    name: str = Field(..., title="Name", description="Name of the network policy to create")
    allowed_network_rule_list: Optional[str] = Field(
        None, title="Allowed Network Rules",
        description="Comma-separated names of allowed network rules",
    )
    blocked_network_rule_list: Optional[str] = Field(
        None, title="Blocked Network Rules",
        description="Comma-separated names of blocked network rules",
    )
    allowed_ip_list: Optional[str] = Field(
        None, title="Allowed IPs", description="Comma-separated list of allowed IPs",
    )
    blocked_ip_list: Optional[str] = Field(
        None, title="Blocked IPs", description="Comma-separated list of blocked IPs",
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the network policy")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the network policy already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchNetworkPolicyConfig(BaseModel):
    """Fetch a single network policy's definition."""

    operation: Literal["fetch_network_policy"] = Field(
        "fetch_network_policy",
        json_schema_extra={
            "const": "fetch_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Fetch Network Policy",
        },
        title="Fetch Network Policy",
    )
    name: str = Field(..., title="Network Policy", description="The network policy to fetch")


class SnowflakeDeleteNetworkPolicyConfig(BaseModel):
    """Drop a network policy."""

    operation: Literal["delete_network_policy"] = Field(
        "delete_network_policy",
        json_schema_extra={
            "const": "delete_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Delete Network Policy",
        },
        title="Delete Network Policy",
    )
    name: str = Field(..., title="Network Policy", description="The network policy to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the network policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsNetworkPolicyConfig(BaseModel):
    """Set a tag on a network policy."""

    operation: Literal["set_tags_network_policy"] = Field(
        "set_tags_network_policy",
        json_schema_extra={
            "const": "set_tags_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Set Tags on Network Policy",
        },
        title="Set Tags on Network Policy",
    )
    name: str = Field(..., title="Network Policy", description="The network policy to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the network policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsNetworkPolicyConfig(BaseModel):
    """Unset a tag from a network policy."""

    operation: Literal["unset_tags_network_policy"] = Field(
        "unset_tags_network_policy",
        json_schema_extra={
            "const": "unset_tags_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Unset Tags from Network Policy",
        },
        title="Unset Tags from Network Policy",
    )
    name: str = Field(..., title="Network Policy", description="The network policy to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the network policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsNetworkPolicyConfig(BaseModel):
    """Get the tag assignments for a network policy."""

    operation: Literal["get_tags_network_policy"] = Field(
        "get_tags_network_policy",
        json_schema_extra={
            "const": "get_tags_network_policy", "ui:hidden": True, "x-category": "Network Policies",
            "x-is-trigger": False, "x-display-name": "Get Tags on Network Policy",
        },
        title="Get Tags on Network Policy",
    )
    name: str = Field(..., title="Network Policy", description="The network policy whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _np_csv(value):
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


async def _list_network_policies(node, c, account, token):
    return await node._request(account, token, "GET", "/network-policies", action_name="list_network_policies")


async def _create_network_policy(node, c, account, token):
    body = {
        "name": c.name,
        "allowed_network_rule_list": _np_csv(c.allowed_network_rule_list),
        "blocked_network_rule_list": _np_csv(c.blocked_network_rule_list),
        "allowed_ip_list": _np_csv(c.allowed_ip_list),
        "blocked_ip_list": _np_csv(c.blocked_ip_list),
        "comment": c.comment,
    }
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/network-policies", params=params, json_body=body, action_name="create_network_policy")


async def _fetch_network_policy(node, c, account, token):
    return await node._request(account, token, "GET", f"/network-policies/{c.name}", action_name="fetch_network_policy")


async def _delete_network_policy(node, c, account, token):
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", f"/network-policies/{c.name}", params=params, action_name="delete_network_policy")


async def _set_tags_network_policy(node, c, account, token):
    ep = f"/network-policies/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_network_policy")


async def _unset_tags_network_policy(node, c, account, token):
    ep = f"/network-policies/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_network_policy")


async def _get_tags_network_policy(node, c, account, token):
    ep = f"/network-policies/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_network_policy")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListNetworkPoliciesConfig,
    SnowflakeCreateNetworkPolicyConfig,
    SnowflakeFetchNetworkPolicyConfig,
    SnowflakeDeleteNetworkPolicyConfig,
    SnowflakeSetTagsNetworkPolicyConfig,
    SnowflakeUnsetTagsNetworkPolicyConfig,
    SnowflakeGetTagsNetworkPolicyConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_network_policies": _list_network_policies,
    "create_network_policy": _create_network_policy,
    "fetch_network_policy": _fetch_network_policy,
    "delete_network_policy": _delete_network_policy,
    "set_tags_network_policy": _set_tags_network_policy,
    "unset_tags_network_policy": _unset_tags_network_policy,
    "get_tags_network_policy": _get_tags_network_policy,
})


# ---- network_rule.py ----
class SnowflakeListNetworkRulesConfig(BaseModel):
    """List network rules in a schema."""

    operation: Literal["list_network_rules"] = Field(
        "list_network_rules",
        json_schema_extra={
            "const": "list_network_rules", "ui:hidden": True, "x-category": "Network Rules",
            "x-is-trigger": False, "x-display-name": "List Network Rules",
        },
        title="List Network Rules",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateNetworkRuleConfig(BaseModel):
    """Create a network rule in a schema."""

    operation: Literal["create_network_rule"] = Field(
        "create_network_rule",
        json_schema_extra={
            "const": "create_network_rule", "ui:hidden": True, "x-category": "Network Rules",
            "x-is-trigger": False, "x-display-name": "Create Network Rule",
        },
        title="Create Network Rule",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the network rule to create")
    type: str = Field(..., title="Type", description="Type of the network rule")
    mode: Optional[str] = Field(
        None, title="Mode",
        description="What is restricted by the network rule",
        json_schema_extra={"enum": ["INGRESS", "INTERNAL_STAGE", "EGRESS"], "x-enum-searchable": True},
    )
    value_list: Optional[str] = Field(None, title="Value List", description="Comma-separated list of values in the network rule")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the network rule")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the network rule already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchNetworkRuleConfig(BaseModel):
    """Fetch a single network rule's definition."""

    operation: Literal["fetch_network_rule"] = Field(
        "fetch_network_rule",
        json_schema_extra={
            "const": "fetch_network_rule", "ui:hidden": True, "x-category": "Network Rules",
            "x-is-trigger": False, "x-display-name": "Fetch Network Rule",
        },
        title="Fetch Network Rule",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Network Rule", description="The network rule to fetch")


class SnowflakeDeleteNetworkRuleConfig(BaseModel):
    """Drop a network rule."""

    operation: Literal["delete_network_rule"] = Field(
        "delete_network_rule",
        json_schema_extra={
            "const": "delete_network_rule", "ui:hidden": True, "x-category": "Network Rules",
            "x-is-trigger": False, "x-display-name": "Delete Network Rule",
        },
        title="Delete Network Rule",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Network Rule", description="The network rule to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the network rule is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_network_rules(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/network-rules"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_network_rules")


async def _create_network_rule(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/network-rules"
    value_list = [v.strip() for v in c.value_list.split(",") if v.strip()] if c.value_list else None
    body = {"name": c.name, "type": c.type, "mode": c.mode, "value_list": value_list, "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_network_rule")


async def _fetch_network_rule(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/network-rules/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_network_rule")


async def _delete_network_rule(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/network-rules/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_network_rule")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListNetworkRulesConfig,
    SnowflakeCreateNetworkRuleConfig,
    SnowflakeFetchNetworkRuleConfig,
    SnowflakeDeleteNetworkRuleConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_network_rules": _list_network_rules,
    "create_network_rule": _create_network_rule,
    "fetch_network_rule": _fetch_network_rule,
    "delete_network_rule": _delete_network_rule,
})


# ---- notebook.py ----
class SnowflakeListNotebooksConfig(BaseModel):
    """List notebooks in a schema."""

    operation: Literal["list_notebooks"] = Field(
        "list_notebooks",
        json_schema_extra={
            "const": "list_notebooks", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "List Notebooks",
        },
        title="List Notebooks",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateNotebookConfig(BaseModel):
    """Create a notebook in a schema."""

    operation: Literal["create_notebook"] = Field(
        "create_notebook",
        json_schema_extra={
            "const": "create_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Create Notebook",
        },
        title="Create Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the notebook to create")
    version: Optional[str] = Field(None, title="Version", description="User specified version alias")
    from_location: Optional[str] = Field(None, title="From Location", description="Snowflake stage location to copy the file from")
    main_file: Optional[str] = Field(None, title="Main File", description="Name + path of the file for the notebook")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the notebook")
    default_version: Optional[str] = Field(None, title="Default Version", description="The default version name of a file based entity")
    query_warehouse: Optional[str] = Field(None, title="Query Warehouse", description="Warehouse the notebook app queries run against")
    title: Optional[str] = Field(None, title="Title", description="User facing title of the notebook app")
    runtime_name: Optional[str] = Field(None, title="Runtime Name", description="The runtime to run the notebook on")
    compute_pool: Optional[str] = Field(None, title="Compute Pool", description="Compute pool name where the notebook runs")
    import_urls: Optional[str] = Field(None, title="Import URLs", description="Comma-separated list of stage files to import")
    external_access_integrations: Optional[str] = Field(None, title="External Access Integrations", description="Comma-separated external access integrations attached to the notebook")
    idle_auto_shutdown_time_seconds: Optional[str] = Field(None, title="Idle Auto Shutdown (s)", description="Seconds before an idle notebook shuts down")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the notebook already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchNotebookConfig(BaseModel):
    """Fetch a single notebook's definition."""

    operation: Literal["fetch_notebook"] = Field(
        "fetch_notebook",
        json_schema_extra={
            "const": "fetch_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Fetch Notebook",
        },
        title="Fetch Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to fetch")


class SnowflakeDeleteNotebookConfig(BaseModel):
    """Drop a notebook."""

    operation: Literal["delete_notebook"] = Field(
        "delete_notebook",
        json_schema_extra={
            "const": "delete_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Delete Notebook",
        },
        title="Delete Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notebook is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeExecuteNotebookConfig(BaseModel):
    """Execute a notebook."""

    operation: Literal["execute_notebook"] = Field(
        "execute_notebook",
        json_schema_extra={
            "const": "execute_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Execute Notebook",
        },
        title="Execute Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to execute")
    async_exec: Optional[str] = Field(
        None, title="Async", description="Execute the notebook asynchronously",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRenameNotebookConfig(BaseModel):
    """Rename a notebook to a new identifier."""

    operation: Literal["rename_notebook"] = Field(
        "rename_notebook",
        json_schema_extra={
            "const": "rename_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Rename Notebook",
        },
        title="Rename Notebook",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Notebook", description="The notebook to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed notebook")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notebook is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeAddLiveVersionNotebookConfig(BaseModel):
    """Add a LIVE version to a notebook."""

    operation: Literal["add_live_version_notebook"] = Field(
        "add_live_version_notebook",
        json_schema_extra={
            "const": "add_live_version_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Add Live Version to Notebook",
        },
        title="Add Live Version to Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to add a LIVE version to")
    from_last: Optional[str] = Field(
        None, title="From Last", description="Set the LIVE version to the LAST version of the notebook",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the notebook version")


class SnowflakeCommitNotebookConfig(BaseModel):
    """Commit the LIVE version of a notebook to its Git repository."""

    operation: Literal["commit_notebook"] = Field(
        "commit_notebook",
        json_schema_extra={
            "const": "commit_notebook", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Commit Notebook",
        },
        title="Commit Notebook",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to commit")
    version: Optional[str] = Field(None, title="Version", description="Live version of the alias")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the notebook version")


class SnowflakeSetNotebookTagsConfig(BaseModel):
    """Set a tag on a notebook."""

    operation: Literal["set_notebook_tags"] = Field(
        "set_notebook_tags",
        json_schema_extra={
            "const": "set_notebook_tags", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Set Notebook Tags",
        },
        title="Set Notebook Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notebook is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetNotebookTagsConfig(BaseModel):
    """Unset a tag from a notebook."""

    operation: Literal["unset_notebook_tags"] = Field(
        "unset_notebook_tags",
        json_schema_extra={
            "const": "unset_notebook_tags", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Unset Notebook Tags",
        },
        title="Unset Notebook Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notebook is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetNotebookTagsConfig(BaseModel):
    """Get the tag assignments for a notebook (requires an active warehouse)."""

    operation: Literal["get_notebook_tags"] = Field(
        "get_notebook_tags",
        json_schema_extra={
            "const": "get_notebook_tags", "ui:hidden": True, "x-category": "Notebooks",
            "x-is-trigger": False, "x-display-name": "Get Notebook Tags",
        },
        title="Get Notebook Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Notebook", description="The notebook to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_notebook_csv(value):
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


async def _list_notebooks(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_notebooks")


async def _create_notebook(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks"
    body = {"name": c.name, "version": c.version, "fromLocation": c.from_location,
            "main_file": c.main_file, "comment": c.comment, "default_version": c.default_version,
            "query_warehouse": c.query_warehouse, "title": c.title, "runtime_name": c.runtime_name,
            "compute_pool": c.compute_pool, "import_urls": _sf_notebook_csv(c.import_urls),
            "external_access_integrations": _sf_notebook_csv(c.external_access_integrations),
            "idle_auto_shutdown_time_seconds": _sf_int(c.idle_auto_shutdown_time_seconds)}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_notebook")


async def _fetch_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_notebook")


async def _delete_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_notebook")


async def _execute_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:execute"
    params = {"asyncExec": _sf_bool(c.async_exec)}
    return await node._request(account, token, "POST", ep, params=params, action_name="execute_notebook")


async def _rename_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_notebook")


async def _add_live_version_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:add-live-version"
    params = {"fromLast": _sf_bool(c.from_last), "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params, action_name="add_live_version_notebook")


async def _commit_notebook(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:commit"
    params = {"version": c.version, "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params, action_name="commit_notebook")


async def _set_notebook_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_notebook_tags")


async def _unset_notebook_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_notebook_tags")


async def _get_notebook_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/notebooks/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_notebook_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListNotebooksConfig,
    SnowflakeCreateNotebookConfig,
    SnowflakeFetchNotebookConfig,
    SnowflakeDeleteNotebookConfig,
    SnowflakeExecuteNotebookConfig,
    SnowflakeRenameNotebookConfig,
    SnowflakeAddLiveVersionNotebookConfig,
    SnowflakeCommitNotebookConfig,
    SnowflakeSetNotebookTagsConfig,
    SnowflakeUnsetNotebookTagsConfig,
    SnowflakeGetNotebookTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_notebooks": _list_notebooks,
    "create_notebook": _create_notebook,
    "fetch_notebook": _fetch_notebook,
    "delete_notebook": _delete_notebook,
    "execute_notebook": _execute_notebook,
    "rename_notebook": _rename_notebook,
    "add_live_version_notebook": _add_live_version_notebook,
    "commit_notebook": _commit_notebook,
    "set_notebook_tags": _set_notebook_tags,
    "unset_notebook_tags": _unset_notebook_tags,
    "get_notebook_tags": _get_notebook_tags,
})


# ---- notification_integration.py ----
class SnowflakeListNotificationIntegrationsConfig(BaseModel):
    """List notification integrations in the account."""

    operation: Literal["list_notification_integrations"] = Field(
        "list_notification_integrations",
        json_schema_extra={
            "const": "list_notification_integrations", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "List Notification Integrations",
        },
        title="List Notification Integrations",
    )
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateNotificationIntegrationConfig(BaseModel):
    """Create a notification integration."""

    operation: Literal["create_notification_integration"] = Field(
        "create_notification_integration",
        json_schema_extra={
            "const": "create_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Create Notification Integration",
        },
        title="Create Notification Integration",
    )
    name: str = Field(..., title="Name", description="Name of the notification integration to create")
    hook_type: str = Field(
        ..., title="Hook Type", description="Type of notification hook",
        json_schema_extra={"enum": [
            "EMAIL", "WEBHOOK", "QUEUE_AWS_SNS_OUTBOUND", "QUEUE_AZURE_EVENT_GRID_OUTBOUND",
            "QUEUE_GCP_PUBSUB_OUTBOUND", "QUEUE_AZURE_EVENT_GRID_INBOUND", "QUEUE_GCP_PUBSUB_INBOUND",
        ], "x-enum-searchable": True},
    )
    allowed_recipients: Optional[str] = Field(
        None, title="Allowed Recipients",
        description="Comma-separated quoted email addresses allowed to receive notifications (EMAIL hook)")
    default_recipients: Optional[str] = Field(
        None, title="Default Recipients",
        description="Comma-separated default recipient email addresses (EMAIL hook)")
    default_subject: Optional[str] = Field(
        None, title="Default Subject", description="Default subject line for sent messages (EMAIL hook)")
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="URL for the webhook; must use https:// (WEBHOOK hook)")
    webhook_body_template: Optional[str] = Field(
        None, title="Webhook Body Template", description="Template for the HTTP request body (WEBHOOK hook)")
    webhook_secret_name: Optional[str] = Field(
        None, title="Webhook Secret Name", description="Name of the secret used with the webhook (WEBHOOK hook)")
    webhook_secret_database_name: Optional[str] = Field(
        None, title="Webhook Secret Database", description="Database storing the webhook secret (WEBHOOK hook)")
    webhook_secret_schema_name: Optional[str] = Field(
        None, title="Webhook Secret Schema", description="Schema storing the webhook secret (WEBHOOK hook)")
    webhook_headers: Optional[str] = Field(
        None, title="Webhook Headers",
        description="HTTP headers for the webhook request, one 'Header: value' per line (WEBHOOK hook)")
    aws_sns_topic_arn: Optional[str] = Field(
        None, title="AWS SNS Topic ARN", description="ARN of the SNS topic notifications are pushed to (AWS SNS hook)")
    aws_sns_role_arn: Optional[str] = Field(
        None, title="AWS SNS Role ARN", description="ARN of the IAM role permitted to publish to the SNS topic (AWS SNS hook)")
    azure_event_grid_topic_endpoint: Optional[str] = Field(
        None, title="Azure Event Grid Topic Endpoint",
        description="Event Grid topic endpoint notifications are pushed to (Azure Event Grid outbound hook)")
    azure_storage_queue_primary_uri: Optional[str] = Field(
        None, title="Azure Storage Queue Primary URI",
        description="Queue ID for the Azure Queue Storage queue (Azure Event Grid inbound hook)")
    azure_tenant_id: Optional[str] = Field(
        None, title="Azure Tenant ID", description="ID of the Azure Active Directory tenant (Azure hooks)")
    gcp_pubsub_topic_name: Optional[str] = Field(
        None, title="GCP Pub/Sub Topic Name",
        description="Pub/Sub topic notifications are pushed to (GCP Pub/Sub outbound hook)")
    gcp_pubsub_subscription_name: Optional[str] = Field(
        None, title="GCP Pub/Sub Subscription Name",
        description="Pub/Sub subscription ID allowing Snowflake access to messages (GCP Pub/Sub inbound hook)")
    enabled: Optional[str] = Field(
        None, title="Enabled", description="Whether the notification integration is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the notification integration")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the notification integration already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchNotificationIntegrationConfig(BaseModel):
    """Fetch a single notification integration's definition."""

    operation: Literal["fetch_notification_integration"] = Field(
        "fetch_notification_integration",
        json_schema_extra={
            "const": "fetch_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Fetch Notification Integration",
        },
        title="Fetch Notification Integration",
    )
    name: str = Field(..., title="Notification Integration", description="The notification integration to fetch")


class SnowflakeDeleteNotificationIntegrationConfig(BaseModel):
    """Drop a notification integration."""

    operation: Literal["delete_notification_integration"] = Field(
        "delete_notification_integration",
        json_schema_extra={
            "const": "delete_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Delete Notification Integration",
        },
        title="Delete Notification Integration",
    )
    name: str = Field(..., title="Notification Integration", description="The notification integration to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notification integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsNotificationIntegrationConfig(BaseModel):
    """Set a tag on a notification integration."""

    operation: Literal["set_tags_notification_integration"] = Field(
        "set_tags_notification_integration",
        json_schema_extra={
            "const": "set_tags_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Set Tags on Notification Integration",
        },
        title="Set Tags on Notification Integration",
    )
    name: str = Field(..., title="Notification Integration", description="The notification integration to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notification integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsNotificationIntegrationConfig(BaseModel):
    """Unset a tag from a notification integration."""

    operation: Literal["unset_tags_notification_integration"] = Field(
        "unset_tags_notification_integration",
        json_schema_extra={
            "const": "unset_tags_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Unset Tags from Notification Integration",
        },
        title="Unset Tags from Notification Integration",
    )
    name: str = Field(..., title="Notification Integration", description="The notification integration to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the notification integration is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsNotificationIntegrationConfig(BaseModel):
    """Get the tag assignments for a notification integration."""

    operation: Literal["get_tags_notification_integration"] = Field(
        "get_tags_notification_integration",
        json_schema_extra={
            "const": "get_tags_notification_integration", "ui:hidden": True, "x-category": "Notification Integrations",
            "x-is-trigger": False, "x-display-name": "Get Tags on Notification Integration",
        },
        title="Get Tags on Notification Integration",
    )
    name: str = Field(..., title="Notification Integration", description="The notification integration whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_ni_csv(value):
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _sf_ni_headers(value):
    if value is None:
        return None
    out = {}
    for line in value.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        if key:
            out[key] = val.strip()
    return out or None


def _sf_notification_integration_body(c):
    hook = {"type": c.hook_type}
    for key, val in (
        ("default_subject", c.default_subject),
        ("webhook_url", c.webhook_url),
        ("webhook_body_template", c.webhook_body_template),
        ("aws_sns_topic_arn", c.aws_sns_topic_arn),
        ("aws_sns_role_arn", c.aws_sns_role_arn),
        ("azure_event_grid_topic_endpoint", c.azure_event_grid_topic_endpoint),
        ("azure_storage_queue_primary_uri", c.azure_storage_queue_primary_uri),
        ("azure_tenant_id", c.azure_tenant_id),
        ("gcp_pubsub_topic_name", c.gcp_pubsub_topic_name),
        ("gcp_pubsub_subscription_name", c.gcp_pubsub_subscription_name),
    ):
        if val is not None:
            hook[key] = val
    if _sf_ni_csv(c.allowed_recipients) is not None:
        hook["allowed_recipients"] = _sf_ni_csv(c.allowed_recipients)
    if _sf_ni_csv(c.default_recipients) is not None:
        hook["default_recipients"] = _sf_ni_csv(c.default_recipients)
    if c.webhook_secret_name is not None:
        secret = {"name": c.webhook_secret_name}
        if c.webhook_secret_database_name is not None:
            secret["database_name"] = c.webhook_secret_database_name
        if c.webhook_secret_schema_name is not None:
            secret["schema_name"] = c.webhook_secret_schema_name
        hook["webhook_secret"] = secret
    headers = _sf_ni_headers(c.webhook_headers)
    if headers is not None:
        hook["webhook_headers"] = headers
    return {
        "name": c.name,
        "notification_hook": hook,
        "enabled": _sf_bool(c.enabled),
        "comment": c.comment,
    }


async def _list_notification_integrations(node, c, account, token):
    params = {"like": c.like}
    return await node._request(account, token, "GET", "/notification-integrations", params=params, action_name="list_notification_integrations")


async def _create_notification_integration(node, c, account, token):
    body = _sf_notification_integration_body(c)
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/notification-integrations", params=params, json_body=body, action_name="create_notification_integration")


async def _fetch_notification_integration(node, c, account, token):
    return await node._request(account, token, "GET", f"/notification-integrations/{c.name}", action_name="fetch_notification_integration")


async def _delete_notification_integration(node, c, account, token):
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", f"/notification-integrations/{c.name}", params=params, action_name="delete_notification_integration")


async def _set_tags_notification_integration(node, c, account, token):
    ep = f"/notification-integrations/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_notification_integration")


async def _unset_tags_notification_integration(node, c, account, token):
    ep = f"/notification-integrations/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_notification_integration")


async def _get_tags_notification_integration(node, c, account, token):
    ep = f"/notification-integrations/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_notification_integration")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListNotificationIntegrationsConfig,
    SnowflakeCreateNotificationIntegrationConfig,
    SnowflakeFetchNotificationIntegrationConfig,
    SnowflakeDeleteNotificationIntegrationConfig,
    SnowflakeSetTagsNotificationIntegrationConfig,
    SnowflakeUnsetTagsNotificationIntegrationConfig,
    SnowflakeGetTagsNotificationIntegrationConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_notification_integrations": _list_notification_integrations,
    "create_notification_integration": _create_notification_integration,
    "fetch_notification_integration": _fetch_notification_integration,
    "delete_notification_integration": _delete_notification_integration,
    "set_tags_notification_integration": _set_tags_notification_integration,
    "unset_tags_notification_integration": _unset_tags_notification_integration,
    "get_tags_notification_integration": _get_tags_notification_integration,
})


# ---- password_policy.py ----
class SnowflakeListPasswordPoliciesConfig(BaseModel):
    """List password policies in a schema."""

    operation: Literal["list_password_policies"] = Field(
        "list_password_policies",
        json_schema_extra={
            "const": "list_password_policies", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "List Password Policies",
        },
        title="List Password Policies",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeCreatePasswordPolicyConfig(BaseModel):
    """Create a password policy in a schema."""

    operation: Literal["create_password_policy"] = Field(
        "create_password_policy",
        json_schema_extra={
            "const": "create_password_policy", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Create Password Policy",
        },
        title="Create Password Policy",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the password policy to create")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the password policy")
    password_min_length: Optional[str] = Field(None, title="Min Length", description="Minimum length of new password")
    password_max_length: Optional[str] = Field(None, title="Max Length", description="Maximum length of new password")
    password_min_upper_case_chars: Optional[str] = Field(None, title="Min Uppercase Chars", description="Minimum number of uppercase characters")
    password_min_lower_case_chars: Optional[str] = Field(None, title="Min Lowercase Chars", description="Minimum number of lowercase characters")
    password_min_numeric_chars: Optional[str] = Field(None, title="Min Numeric Chars", description="Minimum number of numeric characters")
    password_min_special_chars: Optional[str] = Field(None, title="Min Special Chars", description="Minimum number of special characters")
    password_min_age_days: Optional[str] = Field(None, title="Min Age Days", description="Days before a password can be changed again")
    password_max_age_days: Optional[str] = Field(None, title="Max Age Days", description="Days after which password must be changed")
    password_max_retries: Optional[str] = Field(None, title="Max Retries", description="Attempts before account is locked")
    password_lockout_time_mins: Optional[str] = Field(None, title="Lockout Time Mins", description="Minutes users are locked out after max retries")
    password_history: Optional[str] = Field(None, title="Password History", description="Distinct passwords required before re-use")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the password policy already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchPasswordPolicyConfig(BaseModel):
    """Fetch a single password policy's definition."""

    operation: Literal["fetch_password_policy"] = Field(
        "fetch_password_policy",
        json_schema_extra={
            "const": "fetch_password_policy", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Fetch Password Policy",
        },
        title="Fetch Password Policy",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Password Policy", description="The password policy to fetch")


class SnowflakeDeletePasswordPolicyConfig(BaseModel):
    """Drop a password policy."""

    operation: Literal["delete_password_policy"] = Field(
        "delete_password_policy",
        json_schema_extra={
            "const": "delete_password_policy", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Delete Password Policy",
        },
        title="Delete Password Policy",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Password Policy", description="The password policy to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the password policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRenamePasswordPolicyConfig(BaseModel):
    """Rename a password policy to a new identifier."""

    operation: Literal["rename_password_policy"] = Field(
        "rename_password_policy",
        json_schema_extra={
            "const": "rename_password_policy", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Rename Password Policy",
        },
        title="Rename Password Policy",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Password Policy", description="The password policy to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed password policy")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the password policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetPasswordPolicyTagsConfig(BaseModel):
    """Set a tag on a password policy."""

    operation: Literal["set_password_policy_tags"] = Field(
        "set_password_policy_tags",
        json_schema_extra={
            "const": "set_password_policy_tags", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Set Password Policy Tags",
        },
        title="Set Password Policy Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Password Policy", description="The password policy to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the password policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetPasswordPolicyTagsConfig(BaseModel):
    """Unset a tag from a password policy."""

    operation: Literal["unset_password_policy_tags"] = Field(
        "unset_password_policy_tags",
        json_schema_extra={
            "const": "unset_password_policy_tags", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Unset Password Policy Tags",
        },
        title="Unset Password Policy Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Password Policy", description="The password policy to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the password policy is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetPasswordPolicyTagsConfig(BaseModel):
    """Get the tag assignments for a password policy."""

    operation: Literal["get_password_policy_tags"] = Field(
        "get_password_policy_tags",
        json_schema_extra={
            "const": "get_password_policy_tags", "ui:hidden": True, "x-category": "Password Policies",
            "x-is-trigger": False, "x-display-name": "Get Password Policy Tags",
        },
        title="Get Password Policy Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Password Policy", description="The password policy to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_password_policies(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit}
    return await node._request(account, token, "GET", base, params=params, action_name="list_password_policies")


async def _create_password_policy(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies"
    body = {
        "name": c.name, "comment": c.comment,
        "password_min_length": _sf_int(c.password_min_length),
        "password_max_length": _sf_int(c.password_max_length),
        "password_min_upper_case_chars": _sf_int(c.password_min_upper_case_chars),
        "password_min_lower_case_chars": _sf_int(c.password_min_lower_case_chars),
        "password_min_numeric_chars": _sf_int(c.password_min_numeric_chars),
        "password_min_special_chars": _sf_int(c.password_min_special_chars),
        "password_min_age_days": _sf_int(c.password_min_age_days),
        "password_max_age_days": _sf_int(c.password_max_age_days),
        "password_max_retries": _sf_int(c.password_max_retries),
        "password_lockout_time_mins": _sf_int(c.password_lockout_time_mins),
        "password_history": _sf_int(c.password_history),
    }
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_password_policy")


async def _fetch_password_policy(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_password_policy")


async def _delete_password_policy(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_password_policy")


async def _rename_password_policy(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_password_policy")


async def _set_password_policy_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_password_policy_tags")


async def _unset_password_policy_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_password_policy_tags")


async def _get_password_policy_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/password-policies/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_password_policy_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListPasswordPoliciesConfig,
    SnowflakeCreatePasswordPolicyConfig,
    SnowflakeFetchPasswordPolicyConfig,
    SnowflakeDeletePasswordPolicyConfig,
    SnowflakeRenamePasswordPolicyConfig,
    SnowflakeSetPasswordPolicyTagsConfig,
    SnowflakeUnsetPasswordPolicyTagsConfig,
    SnowflakeGetPasswordPolicyTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_password_policies": _list_password_policies,
    "create_password_policy": _create_password_policy,
    "fetch_password_policy": _fetch_password_policy,
    "delete_password_policy": _delete_password_policy,
    "rename_password_policy": _rename_password_policy,
    "set_password_policy_tags": _set_password_policy_tags,
    "unset_password_policy_tags": _unset_password_policy_tags,
    "get_password_policy_tags": _get_password_policy_tags,
})


# ---- pipe.py ----
class SnowflakeListPipesConfig(BaseModel):
    """List pipes in a schema."""

    operation: Literal["list_pipes"] = Field(
        "list_pipes",
        json_schema_extra={
            "const": "list_pipes", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "List Pipes",
        },
        title="List Pipes",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreatePipeConfig(BaseModel):
    """Create a pipe in a schema."""

    operation: Literal["create_pipe"] = Field(
        "create_pipe",
        json_schema_extra={
            "const": "create_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Create Pipe",
        },
        title="Create Pipe",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the pipe to create")
    copy_statement: str = Field(
        ..., title="Copy Statement",
        description="COPY INTO <table> statement used to load data from queued files",
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the pipe")
    auto_ingest: Optional[str] = Field(
        None, title="Auto Ingest", description="Auto-ingest all files from the stage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    error_integration: Optional[str] = Field(
        None, title="Error Integration",
        description="Integration object pointing to a user-provided Azure storage queue / SQS for error notifications",
    )
    aws_sns_topic: Optional[str] = Field(
        None, title="AWS SNS Topic",
        description="If provided, an auto_ingest pipe only receives messages from this SNS topic",
    )
    integration: Optional[str] = Field(
        None, title="Integration",
        description="Integration object tying a user-provided storage queue to an auto_ingest pipe (required on Azure)",
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the pipe already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchPipeConfig(BaseModel):
    """Fetch a single pipe's definition."""

    operation: Literal["fetch_pipe"] = Field(
        "fetch_pipe",
        json_schema_extra={
            "const": "fetch_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Fetch Pipe",
        },
        title="Fetch Pipe",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to fetch")


class SnowflakeDeletePipeConfig(BaseModel):
    """Drop a pipe."""

    operation: Literal["delete_pipe"] = Field(
        "delete_pipe",
        json_schema_extra={
            "const": "delete_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Delete Pipe",
        },
        title="Delete Pipe",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the pipe is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeRefreshPipeConfig(BaseModel):
    """Refresh a pipe to load staged files into the ingest queue."""

    operation: Literal["refresh_pipe"] = Field(
        "refresh_pipe",
        json_schema_extra={
            "const": "refresh_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Refresh Pipe",
        },
        title="Refresh Pipe",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to refresh")
    prefix: Optional[str] = Field(
        None, title="Prefix",
        description="Path (or prefix) appended to the stage reference, limiting the set of files to load",
    )
    modified_after: Optional[str] = Field(
        None, title="Modified After",
        description="ISO-8601 timestamp of the oldest data files to copy based on LAST_MODIFIED date",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the pipe is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsPipeConfig(BaseModel):
    """Set a tag on a pipe."""

    operation: Literal["set_tags_pipe"] = Field(
        "set_tags_pipe",
        json_schema_extra={
            "const": "set_tags_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Set Pipe Tags",
        },
        title="Set Pipe Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the pipe is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsPipeConfig(BaseModel):
    """Unset a tag from a pipe."""

    operation: Literal["unset_tags_pipe"] = Field(
        "unset_tags_pipe",
        json_schema_extra={
            "const": "unset_tags_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Unset Pipe Tags",
        },
        title="Unset Pipe Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the pipe is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsPipeConfig(BaseModel):
    """Get the tag assignments for a pipe (requires an active warehouse)."""

    operation: Literal["get_tags_pipe"] = Field(
        "get_tags_pipe",
        json_schema_extra={
            "const": "get_tags_pipe", "ui:hidden": True, "x-category": "Pipes",
            "x-is-trigger": False, "x-display-name": "Get Pipe Tags",
        },
        title="Get Pipe Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Pipe", description="The pipe to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_pipes(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/pipes"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_pipes")


async def _create_pipe(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/pipes"
    body = {"name": c.name, "copy_statement": c.copy_statement, "comment": c.comment,
            "auto_ingest": _sf_bool(c.auto_ingest), "error_integration": c.error_integration,
            "aws_sns_topic": c.aws_sns_topic, "integration": c.integration}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_pipe")


async def _fetch_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_pipe")


async def _delete_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_pipe")


async def _refresh_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}:refresh"
    params = {"ifExists": _sf_bool(c.if_exists), "prefix": c.prefix, "modified_after": c.modified_after}
    return await node._request(account, token, "POST", ep, params=params, action_name="refresh_pipe")


async def _set_tags_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_pipe")


async def _unset_tags_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_pipe")


async def _get_tags_pipe(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/pipes/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_pipe")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListPipesConfig,
    SnowflakeCreatePipeConfig,
    SnowflakeFetchPipeConfig,
    SnowflakeDeletePipeConfig,
    SnowflakeRefreshPipeConfig,
    SnowflakeSetTagsPipeConfig,
    SnowflakeUnsetTagsPipeConfig,
    SnowflakeGetTagsPipeConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_pipes": _list_pipes,
    "create_pipe": _create_pipe,
    "fetch_pipe": _fetch_pipe,
    "delete_pipe": _delete_pipe,
    "refresh_pipe": _refresh_pipe,
    "set_tags_pipe": _set_tags_pipe,
    "unset_tags_pipe": _unset_tags_pipe,
    "get_tags_pipe": _get_tags_pipe,
})


# ---- procedure.py ----
class SnowflakeListProceduresConfig(BaseModel):
    """List procedures in a schema."""

    operation: Literal["list_procedures"] = Field(
        "list_procedures",
        json_schema_extra={
            "const": "list_procedures", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "List Procedures",
        },
        title="List Procedures",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateProcedureConfig(BaseModel):
    """Create a procedure in a schema."""

    operation: Literal["create_procedure"] = Field(
        "create_procedure",
        json_schema_extra={
            "const": "create_procedure", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Create Procedure",
        },
        title="Create Procedure",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the procedure to create")
    arguments: Optional[str] = Field(
        None, title="Arguments",
        description="JSON array of procedure arguments, e.g. [{\"name\":\"x\",\"datatype\":\"TEXT\"}]",
    )
    return_type: Optional[str] = Field(
        None, title="Return Type",
        description="JSON return type object, e.g. {\"type\":\"DATATYPE\",\"datatype\":\"TEXT\"}",
    )
    language_config: Optional[str] = Field(
        None, title="Language Config",
        description="JSON language config, e.g. {\"language\":\"SQL\"}",
    )
    execute_as: Optional[str] = Field(
        None, title="Execute As",
        description="Permissions the procedure executes with",
        json_schema_extra={"enum": ["CALLER", "OWNER"], "x-enum-searchable": True},
    )
    is_secure: Optional[str] = Field(
        None, title="Is Secure", description="Whether the procedure is secure",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the procedure")
    body: Optional[str] = Field(None, title="Body", description="Procedure definition")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the procedure already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Retain access privileges from the original procedure on replace",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchProcedureConfig(BaseModel):
    """Fetch a single procedure's definition."""

    operation: Literal["fetch_procedure"] = Field(
        "fetch_procedure",
        json_schema_extra={
            "const": "fetch_procedure", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Fetch Procedure",
        },
        title="Fetch Procedure",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")


class SnowflakeDeleteProcedureConfig(BaseModel):
    """Drop a procedure."""

    operation: Literal["delete_procedure"] = Field(
        "delete_procedure",
        json_schema_extra={
            "const": "delete_procedure", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Delete Procedure",
        },
        title="Delete Procedure",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the procedure is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCallProcedureConfig(BaseModel):
    """Call a procedure with arguments."""

    operation: Literal["call_procedure"] = Field(
        "call_procedure",
        json_schema_extra={
            "const": "call_procedure", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Call Procedure",
        },
        title="Call Procedure",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")
    call_arguments: Optional[str] = Field(
        None, title="Call Arguments",
        description="JSON array of call arguments, e.g. [{\"name\":\"x\",\"datatype\":\"TEXT\",\"value\":\"hi\"}]",
    )


class SnowflakeSetProcedureTagsConfig(BaseModel):
    """Set tags on a procedure."""

    operation: Literal["set_procedure_tags"] = Field(
        "set_procedure_tags",
        json_schema_extra={
            "const": "set_procedure_tags", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Set Procedure Tags",
        },
        title="Set Procedure Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")
    tags: Optional[str] = Field(
        None, title="Tags",
        description="JSON array of tag assignments, e.g. [{\"name\":\"cost_center\",\"value\":\"eng\"}]",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the procedure is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetProcedureTagsConfig(BaseModel):
    """Unset tags from a procedure."""

    operation: Literal["unset_procedure_tags"] = Field(
        "unset_procedure_tags",
        json_schema_extra={
            "const": "unset_procedure_tags", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Unset Procedure Tags",
        },
        title="Unset Procedure Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")
    tags: Optional[str] = Field(
        None, title="Tags",
        description="JSON array of tag names to unset, e.g. [{\"name\":\"cost_center\"}]",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the procedure is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetProcedureTagsConfig(BaseModel):
    """Get the tag assignments for a procedure."""

    operation: Literal["get_procedure_tags"] = Field(
        "get_procedure_tags",
        json_schema_extra={
            "const": "get_procedure_tags", "ui:hidden": True, "x-category": "Procedures",
            "x-is-trigger": False, "x-display-name": "Get Procedure Tags",
        },
        title="Get Procedure Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Procedure", description="Procedure name with arguments, e.g. my_proc(TEXT)")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_procedures(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/procedures"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_procedures")


async def _create_procedure(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/procedures"
    body = {"name": c.name, "arguments": c.arguments, "return_type": c.return_type,
            "language_config": c.language_config, "execute_as": c.execute_as,
            "is_secure": _sf_bool(c.is_secure), "comment": c.comment, "body": c.body}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_procedure")


async def _fetch_procedure(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_procedure")


async def _delete_procedure(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_procedure")


async def _call_procedure(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}:call"
    body = {"call_arguments": c.call_arguments}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="call_procedure")


async def _set_procedure_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"tags": c.tags}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_procedure_tags")


async def _unset_procedure_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"tags": c.tags}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_procedure_tags")


async def _get_procedure_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/procedures/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_procedure_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListProceduresConfig,
    SnowflakeCreateProcedureConfig,
    SnowflakeFetchProcedureConfig,
    SnowflakeDeleteProcedureConfig,
    SnowflakeCallProcedureConfig,
    SnowflakeSetProcedureTagsConfig,
    SnowflakeUnsetProcedureTagsConfig,
    SnowflakeGetProcedureTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_procedures": _list_procedures,
    "create_procedure": _create_procedure,
    "fetch_procedure": _fetch_procedure,
    "delete_procedure": _delete_procedure,
    "call_procedure": _call_procedure,
    "set_procedure_tags": _set_procedure_tags,
    "unset_procedure_tags": _unset_procedure_tags,
    "get_procedure_tags": _get_procedure_tags,
})


# ---- role.py ----
class SnowflakeCreateRoleConfig(BaseModel):
    """Create a role."""

    operation: Literal["create_role"] = Field(
        "create_role",
        json_schema_extra={
            "const": "create_role", "x-creates-resource": True, "x-resource-type": "snowflake_role", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Create Role",
        },
        title="Create Role",
    )
    name: str = Field(..., title="Name", description="Name of the role to create")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the role")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the role already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeDeleteRoleConfig(BaseModel):
    """Delete a role."""

    operation: Literal["delete_role"] = Field(
        "delete_role",
        json_schema_extra={
            "const": "delete_role", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Delete Role",
        },
        title="Delete Role",
    )
    name: str = Field(..., title="Name", description="The role to delete")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeListGrantsRoleConfig(BaseModel):
    """List all grants (privileges/roles) granted to the role."""

    operation: Literal["list_grants"] = Field(
        "list_grants",
        json_schema_extra={
            "const": "list_grants", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "List Grants To Role",
        },
        title="List Grants To Role",
    )
    name: str = Field(..., title="Role", description="The role whose grants to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeGrantPrivilegesRoleConfig(BaseModel):
    """Grant privileges to the role."""

    operation: Literal["grant_privileges"] = Field(
        "grant_privileges",
        json_schema_extra={
            "const": "grant_privileges", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Grant Privileges To Role",
        },
        title="Grant Privileges To Role",
    )
    name: str = Field(..., title="Role", description="The role to grant privileges to")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be granted")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Allow the recipient role to re-grant the privileges",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable if applicable")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")


class SnowflakeRevokeGrantsRoleConfig(BaseModel):
    """Revoke grants from the role."""

    operation: Literal["revoke_grants"] = Field(
        "revoke_grants",
        json_schema_extra={
            "const": "revoke_grants", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Revoke Grants From Role",
        },
        title="Revoke Grants From Role",
    )
    name: str = Field(..., title="Role", description="The role to revoke grants from")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be revoked")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to revoke")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Revoke only the grant option, not the privilege",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable if applicable")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")
    mode: Optional[str] = Field(
        None, title="Mode", description="Revoke behavior for dependent grants",
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeListGrantsOfRoleConfig(BaseModel):
    """List all grants of the role (users/roles it is granted to)."""

    operation: Literal["list_grants_of"] = Field(
        "list_grants_of",
        json_schema_extra={
            "const": "list_grants_of", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "List Grants Of Role",
        },
        title="List Grants Of Role",
    )
    name: str = Field(..., title="Role", description="The role whose grantees to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeListGrantsOnRoleConfig(BaseModel):
    """List all grants on the role (privileges held on the role securable)."""

    operation: Literal["list_grants_on"] = Field(
        "list_grants_on",
        json_schema_extra={
            "const": "list_grants_on", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "List Grants On Role",
        },
        title="List Grants On Role",
    )
    name: str = Field(..., title="Role", description="The role whose grants-on to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeListFutureGrantsRoleConfig(BaseModel):
    """List all future grants to the role."""

    operation: Literal["list_future_grants"] = Field(
        "list_future_grants",
        json_schema_extra={
            "const": "list_future_grants", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "List Future Grants To Role",
        },
        title="List Future Grants To Role",
    )
    name: str = Field(..., title="Role", description="The role whose future grants to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeGrantFuturePrivilegesRoleConfig(BaseModel):
    """Grant future privileges to the role."""

    operation: Literal["grant_future_privileges"] = Field(
        "grant_future_privileges",
        json_schema_extra={
            "const": "grant_future_privileges", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Grant Future Privileges To Role",
        },
        title="Grant Future Privileges To Role",
    )
    name: str = Field(..., title="Role", description="The role to grant future privileges to")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be granted")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to grant")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Allow the recipient role to re-grant the privileges",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable if applicable")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")


class SnowflakeRevokeFutureGrantsRoleConfig(BaseModel):
    """Revoke future grants from the role."""

    operation: Literal["revoke_future_grants"] = Field(
        "revoke_future_grants",
        json_schema_extra={
            "const": "revoke_future_grants", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Revoke Future Grants From Role",
        },
        title="Revoke Future Grants From Role",
    )
    name: str = Field(..., title="Role", description="The role to revoke future grants from")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be revoked")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to revoke")
    grant_option: Optional[str] = Field(
        None, title="Grant Option", description="Revoke only the grant option, not the privilege",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_service: Optional[str] = Field(None, title="Securable Service", description="Service name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable if applicable")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")
    mode: Optional[str] = Field(
        None, title="Mode", description="Revoke behavior for dependent grants",
        json_schema_extra={"enum": ["restrict", "cascade"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsRoleConfig(BaseModel):
    """Set tags on a role."""

    operation: Literal["set_tags_role"] = Field(
        "set_tags_role",
        json_schema_extra={
            "const": "set_tags_role", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Set Tags On Role",
        },
        title="Set Tags On Role",
    )
    name: str = Field(..., title="Role", description="The role to tag")
    tags: str = Field(
        ..., title="Tags",
        description='Comma-separated tag assignments as "name=value" pairs, e.g. "cost_center=eng, env=prod"',
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsRoleConfig(BaseModel):
    """Unset tags from a role."""

    operation: Literal["unset_tags_role"] = Field(
        "unset_tags_role",
        json_schema_extra={
            "const": "unset_tags_role", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Unset Tags From Role",
        },
        title="Unset Tags From Role",
    )
    name: str = Field(..., title="Role", description="The role to untag")
    tags: str = Field(..., title="Tag Names", description="Comma-separated tag names to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the role is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsRoleConfig(BaseModel):
    """Get the tag assignments for a role (requires an active warehouse)."""

    operation: Literal["get_tags_role"] = Field(
        "get_tags_role",
        json_schema_extra={
            "const": "get_tags_role", "ui:hidden": True, "x-category": "Roles",
            "x-is-trigger": False, "x-display-name": "Get Tags On Role",
        },
        title="Get Tags On Role",
    )
    name: str = Field(..., title="Role", description="The role whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _role_grant_body(c):
    securable = {k: v for k, v in {
        "database": c.securable_database, "schema": c.securable_schema,
        "service": c.securable_service, "name": c.securable_name}.items() if v}
    containing_scope = {k: v for k, v in {
        "database": c.scope_database, "schema": c.scope_schema}.items() if v}
    body = {
        "securable_type": c.securable_type,
        "grant_option": _sf_bool(c.grant_option),
        "privileges": [p.strip() for p in c.privileges.split(",") if p.strip()] if c.privileges else None,
    }
    if securable:
        body["securable"] = securable
    if containing_scope:
        body["containing_scope"] = containing_scope
    return body


async def _create_role(node, c, account, token):
    body = {"name": c.name, "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", "/roles", params=params, json_body=body, action_name="create_role")


async def _delete_role(node, c, account, token):
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", f"/roles/{c.name}", params=params, action_name="delete_role")


async def _list_grants(node, c, account, token):
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", f"/roles/{c.name}/grants", params=params, action_name="list_grants")


async def _grant_privileges(node, c, account, token):
    return await node._request(account, token, "POST", f"/roles/{c.name}/grants",
                               json_body=_role_grant_body(c), action_name="grant_privileges")


async def _revoke_grants(node, c, account, token):
    params = {"mode": c.mode}
    return await node._request(account, token, "POST", f"/roles/{c.name}/grants:revoke",
                               params=params, json_body=_role_grant_body(c), action_name="revoke_grants")


async def _list_grants_of(node, c, account, token):
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", f"/roles/{c.name}/grants-of", params=params, action_name="list_grants_of")


async def _list_grants_on(node, c, account, token):
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", f"/roles/{c.name}/grants-on", params=params, action_name="list_grants_on")


async def _list_future_grants(node, c, account, token):
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", f"/roles/{c.name}/future-grants", params=params, action_name="list_future_grants")


async def _grant_future_privileges(node, c, account, token):
    return await node._request(account, token, "POST", f"/roles/{c.name}/future-grants",
                               json_body=_role_grant_body(c), action_name="grant_future_privileges")


async def _revoke_future_grants(node, c, account, token):
    params = {"mode": c.mode}
    return await node._request(account, token, "POST", f"/roles/{c.name}/future-grants:revoke",
                               params=params, json_body=_role_grant_body(c), action_name="revoke_future_grants")


async def _set_tags_role(node, c, account, token):
    body = []
    for pair in c.tags.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tag_name, _, tag_value = pair.partition("=")
        body.append({"name": tag_name.strip(), "value": tag_value.strip()})
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/roles/{c.name}:set-tags",
                               params=params, json_body=body, action_name="set_tags_role")


async def _unset_tags_role(node, c, account, token):
    body = [{"name": t.strip()} for t in c.tags.split(",") if t.strip()]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/roles/{c.name}:unset-tags",
                               params=params, json_body=body, action_name="unset_tags_role")


async def _get_tags_role(node, c, account, token):
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", f"/roles/{c.name}:get-tags", params=params, action_name="get_tags_role")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeCreateRoleConfig,
    SnowflakeDeleteRoleConfig,
    SnowflakeListGrantsRoleConfig,
    SnowflakeGrantPrivilegesRoleConfig,
    SnowflakeRevokeGrantsRoleConfig,
    SnowflakeListGrantsOfRoleConfig,
    SnowflakeListGrantsOnRoleConfig,
    SnowflakeListFutureGrantsRoleConfig,
    SnowflakeGrantFuturePrivilegesRoleConfig,
    SnowflakeRevokeFutureGrantsRoleConfig,
    SnowflakeSetTagsRoleConfig,
    SnowflakeUnsetTagsRoleConfig,
    SnowflakeGetTagsRoleConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "create_role": _create_role,
    "delete_role": _delete_role,
    "list_grants": _list_grants,
    "grant_privileges": _grant_privileges,
    "revoke_grants": _revoke_grants,
    "list_grants_of": _list_grants_of,
    "list_grants_on": _list_grants_on,
    "list_future_grants": _list_future_grants,
    "grant_future_privileges": _grant_future_privileges,
    "revoke_future_grants": _revoke_future_grants,
    "set_tags_role": _set_tags_role,
    "unset_tags_role": _unset_tags_role,
    "get_tags_role": _get_tags_role,
})


# ---- schema.py ----
class SnowflakeCreateSchemaConfig(BaseModel):
    """Create a schema in a database."""

    operation: Literal["create_schema"] = Field(
        "create_schema",
        json_schema_extra={
            "const": "create_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Create Schema",
        },
        title="Create Schema",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Name", description="Name of the schema to create")
    kind: Optional[str] = Field(
        None, title="Kind", description="Schema type",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the schema")
    managed_access: Optional[str] = Field(
        None, title="Managed Access", description="Centralize privilege management with the schema owner",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention (days)", description="Time Travel retention period")
    default_ddl_collation: Optional[str] = Field(None, title="Default DDL Collation", description="Default collation for new tables")
    log_level: Optional[str] = Field(None, title="Log Level", description="TRACE, DEBUG, INFO, WARN, ERROR, FATAL or OFF")
    pipe_execution_paused: Optional[str] = Field(
        None, title="Pipe Execution Paused", description="Whether pipe execution is paused",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension (days)", description="Max days Snowflake can extend retention")
    suspend_task_after_num_failures: Optional[str] = Field(None, title="Suspend Task After Failures", description="Consecutive failed runs before auto-suspend")
    trace_level: Optional[str] = Field(None, title="Trace Level", description="ALWAYS, ON_EVENT, or OFF")
    user_task_managed_initial_warehouse_size: Optional[str] = Field(None, title="Initial Warehouse Size", description="Serverless task first-run compute size")
    user_task_timeout_ms: Optional[str] = Field(None, title="User Task Timeout (ms)", description="Time limit for a single task run")
    serverless_task_min_statement_size: Optional[str] = Field(None, title="Min Statement Size", description="Minimum serverless task warehouse size")
    serverless_task_max_statement_size: Optional[str] = Field(None, title="Max Statement Size", description="Maximum serverless task warehouse size")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the schema already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeCloneSchemaConfig(BaseModel):
    """Clone an existing schema into a (possibly different) database."""

    operation: Literal["clone_schema"] = Field(
        "clone_schema",
        json_schema_extra={
            "const": "clone_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Clone Schema",
        },
        title="Clone Schema",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The source schema to clone")
    target_name: str = Field(..., title="New Schema Name", description="Name of the newly created schema")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the new schema")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeUndropSchemaConfig(BaseModel):
    """Restore a dropped schema."""

    operation: Literal["undrop_schema"] = Field(
        "undrop_schema",
        json_schema_extra={
            "const": "undrop_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Undrop Schema",
        },
        title="Undrop Schema",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema to undrop")


class SnowflakeFetchSchemaConfig(BaseModel):
    """Fetch a single schema's definition."""

    operation: Literal["fetch_schema"] = Field(
        "fetch_schema",
        json_schema_extra={
            "const": "fetch_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Fetch Schema",
        },
        title="Fetch Schema",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema to fetch")


class SnowflakeCreateOrAlterSchemaConfig(BaseModel):
    """Create a new, or alter an existing, schema."""

    operation: Literal["create_or_alter_schema"] = Field(
        "create_or_alter_schema",
        json_schema_extra={
            "const": "create_or_alter_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Create or Alter Schema",
        },
        title="Create or Alter Schema",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="Name of the schema")
    kind: Optional[str] = Field(
        None, title="Kind", description="Schema type",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the schema")
    managed_access: Optional[str] = Field(
        None, title="Managed Access", description="Centralize privilege management with the schema owner",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention (days)", description="Time Travel retention period")
    default_ddl_collation: Optional[str] = Field(None, title="Default DDL Collation", description="Default collation for new tables")
    log_level: Optional[str] = Field(None, title="Log Level", description="TRACE, DEBUG, INFO, WARN, ERROR, FATAL or OFF")
    pipe_execution_paused: Optional[str] = Field(
        None, title="Pipe Execution Paused", description="Whether pipe execution is paused",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension (days)", description="Max days Snowflake can extend retention")
    suspend_task_after_num_failures: Optional[str] = Field(None, title="Suspend Task After Failures", description="Consecutive failed runs before auto-suspend")
    trace_level: Optional[str] = Field(None, title="Trace Level", description="ALWAYS, ON_EVENT, or OFF")
    user_task_managed_initial_warehouse_size: Optional[str] = Field(None, title="Initial Warehouse Size", description="Serverless task first-run compute size")
    user_task_timeout_ms: Optional[str] = Field(None, title="User Task Timeout (ms)", description="Time limit for a single task run")
    serverless_task_min_statement_size: Optional[str] = Field(None, title="Min Statement Size", description="Minimum serverless task warehouse size")
    serverless_task_max_statement_size: Optional[str] = Field(None, title="Max Statement Size", description="Maximum serverless task warehouse size")


class SnowflakeDeleteSchemaConfig(BaseModel):
    """Drop a schema."""

    operation: Literal["delete_schema"] = Field(
        "delete_schema",
        json_schema_extra={
            "const": "delete_schema", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Delete Schema",
        },
        title="Delete Schema",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the schema is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    restrict: Optional[str] = Field(
        None, title="Restrict", description="Warn instead of dropping if foreign keys reference the schema's tables",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetSchemaTagsConfig(BaseModel):
    """Set a tag on a schema."""

    operation: Literal["set_schema_tags"] = Field(
        "set_schema_tags",
        json_schema_extra={
            "const": "set_schema_tags", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Set Schema Tags",
        },
        title="Set Schema Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the schema is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetSchemaTagsConfig(BaseModel):
    """Unset tags from a schema."""

    operation: Literal["unset_schema_tags"] = Field(
        "unset_schema_tags",
        json_schema_extra={
            "const": "unset_schema_tags", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Unset Schema Tags",
        },
        title="Unset Schema Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema to untag")
    tag_name: str = Field(..., title="Tag Name(s)", description="Comma-separated tag names to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the schema is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetSchemaTagsConfig(BaseModel):
    """Get the tag assignments for a schema."""

    operation: Literal["get_schema_tags"] = Field(
        "get_schema_tags",
        json_schema_extra={
            "const": "get_schema_tags", "ui:hidden": True, "x-category": "Schemas",
            "x-is-trigger": False, "x-display-name": "Get Schema Tags",
        },
        title="Get Schema Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    name: str = Field(..., title="Schema", description="The schema whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_schema_body(c):
    return {
        "name": c.name,
        "kind": c.kind,
        "comment": c.comment,
        "managed_access": _sf_bool(c.managed_access),
        "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
        "default_ddl_collation": c.default_ddl_collation,
        "log_level": c.log_level,
        "pipe_execution_paused": _sf_bool(c.pipe_execution_paused),
        "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
        "suspend_task_after_num_failures": _sf_int(c.suspend_task_after_num_failures),
        "trace_level": c.trace_level,
        "user_task_managed_initial_warehouse_size": c.user_task_managed_initial_warehouse_size,
        "user_task_timeout_ms": _sf_int(c.user_task_timeout_ms),
        "serverless_task_min_statement_size": c.serverless_task_min_statement_size,
        "serverless_task_max_statement_size": c.serverless_task_max_statement_size,
    }


async def _create_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas"
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=_sf_schema_body(c), action_name="create_schema")


async def _clone_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}:clone"
    params = {"createMode": c.create_mode, "targetDatabase": c.target_database}
    body = {"name": c.target_name, "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="clone_schema")


async def _undrop_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_schema")


async def _fetch_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_schema")


async def _create_or_alter_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}"
    return await node._request(account, token, "PUT", ep,
                               json_body=_sf_schema_body(c), action_name="create_or_alter_schema")


async def _delete_schema(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists), "restrict": _sf_bool(c.restrict)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_schema")


async def _set_schema_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="set_schema_tags")


async def _unset_schema_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": n.strip()} for n in c.tag_name.split(",") if n.strip()]
    return await node._request(account, token, "POST", ep, params=params,
                               json_body=body, action_name="unset_schema_tags")


async def _get_schema_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_schema_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeCreateSchemaConfig,
    SnowflakeCloneSchemaConfig,
    SnowflakeUndropSchemaConfig,
    SnowflakeFetchSchemaConfig,
    SnowflakeCreateOrAlterSchemaConfig,
    SnowflakeDeleteSchemaConfig,
    SnowflakeSetSchemaTagsConfig,
    SnowflakeUnsetSchemaTagsConfig,
    SnowflakeGetSchemaTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "create_schema": _create_schema,
    "clone_schema": _clone_schema,
    "undrop_schema": _undrop_schema,
    "fetch_schema": _fetch_schema,
    "create_or_alter_schema": _create_or_alter_schema,
    "delete_schema": _delete_schema,
    "set_schema_tags": _set_schema_tags,
    "unset_schema_tags": _unset_schema_tags,
    "get_schema_tags": _get_schema_tags,
})


# ---- secret.py ----
class SnowflakeListSecretsConfig(BaseModel):
    """List secrets in a schema."""

    operation: Literal["list_secrets"] = Field(
        "list_secrets",
        json_schema_extra={
            "const": "list_secrets", "ui:hidden": True, "x-category": "Secrets",
            "x-is-trigger": False, "x-display-name": "List Secrets",
        },
        title="List Secrets",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateSecretConfig(BaseModel):
    """Create a secret in a schema."""

    operation: Literal["create_secret"] = Field(
        "create_secret",
        json_schema_extra={
            "const": "create_secret", "ui:hidden": True, "x-category": "Secrets",
            "x-is-trigger": False, "x-display-name": "Create Secret",
        },
        title="Create Secret",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the secret to create")
    type: str = Field(
        ..., title="Type", description="Type of the secret",
        json_schema_extra={"enum": [
            "PASSWORD", "OAUTH2", "GENERIC_STRING", "SYMMETRIC_KEY",
            "CLOUD_PROVIDER_TOKEN", "JWT_KEY_PAIR"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the secret")
    username: Optional[str] = Field(None, title="Username", description="Name of the user (PASSWORD type)")
    password: Optional[str] = Field(None, title="Password", description="Password of the user (PASSWORD type)")
    secret_string: Optional[str] = Field(None, title="Secret String", description="Generic secret string (GENERIC_STRING type)")
    algorithm: Optional[str] = Field(None, title="Algorithm", description="Key secret's algorithm name (SYMMETRIC_KEY / JWT_KEY_PAIR type)")
    key_length: Optional[str] = Field(None, title="Key Length", description="Size of key used in secret (JWT_KEY_PAIR type)")
    api_authentication: Optional[str] = Field(None, title="API Authentication", description="API provider's authentication server integration name (OAUTH2 / CLOUD_PROVIDER_TOKEN type)")
    oauth_refresh_token: Optional[str] = Field(None, title="OAuth Refresh Token", description="OAuth secret refresh token (OAUTH2 type)")
    oauth_refresh_token_expiry_time: Optional[str] = Field(None, title="OAuth Refresh Token Expiry Time", description="Date or timestamp (UTC) when OAuth refresh token will expire (OAUTH2 type)")
    oauth_scopes: Optional[str] = Field(None, title="OAuth Scopes", description="Comma-separated scopes represented during OAuth flow (OAUTH2 type)")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the secret already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchSecretConfig(BaseModel):
    """Fetch a single secret's definition."""

    operation: Literal["fetch_secret"] = Field(
        "fetch_secret",
        json_schema_extra={
            "const": "fetch_secret", "ui:hidden": True, "x-category": "Secrets",
            "x-is-trigger": False, "x-display-name": "Fetch Secret",
        },
        title="Fetch Secret",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Secret", description="The secret to fetch")


class SnowflakeDeleteSecretConfig(BaseModel):
    """Drop a secret."""

    operation: Literal["delete_secret"] = Field(
        "delete_secret",
        json_schema_extra={
            "const": "delete_secret", "ui:hidden": True, "x-category": "Secrets",
            "x-is-trigger": False, "x-display-name": "Delete Secret",
        },
        title="Delete Secret",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Secret", description="The secret to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the secret is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_secrets(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/secrets"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_secrets")


async def _create_secret(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/secrets"
    scopes = [s.strip() for s in c.oauth_scopes.split(",")] if c.oauth_scopes else None
    body = {
        "name": c.name, "type": c.type, "comment": c.comment,
        "username": c.username, "password": c.password,
        "secret_string": c.secret_string, "algorithm": c.algorithm,
        "key_length": _sf_int(c.key_length), "api_authentication": c.api_authentication,
        "oauth_refresh_token": c.oauth_refresh_token,
        "oauth_refresh_token_expiry_time": c.oauth_refresh_token_expiry_time,
        "oauth_scopes": scopes,
    }
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_secret")


async def _fetch_secret(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/secrets/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_secret")


async def _delete_secret(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/secrets/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_secret")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListSecretsConfig,
    SnowflakeCreateSecretConfig,
    SnowflakeFetchSecretConfig,
    SnowflakeDeleteSecretConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_secrets": _list_secrets,
    "create_secret": _create_secret,
    "fetch_secret": _fetch_secret,
    "delete_secret": _delete_secret,
})


# ---- sequence.py ----
class SnowflakeListSequencesConfig(BaseModel):
    """List sequences in a schema."""

    operation: Literal["list_sequences"] = Field(
        "list_sequences",
        json_schema_extra={
            "const": "list_sequences", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "List Sequences",
        },
        title="List Sequences",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateSequenceConfig(BaseModel):
    """Create a sequence in a schema."""

    operation: Literal["create_sequence"] = Field(
        "create_sequence",
        json_schema_extra={
            "const": "create_sequence", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "Create Sequence",
        },
        title="Create Sequence",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the sequence to create")
    start: Optional[str] = Field(None, title="Start", description="First value returned by the sequence")
    increment: Optional[str] = Field(None, title="Increment", description="Step interval of the sequence")
    ordered: Optional[str] = Field(
        None, title="Ordered", description="Whether values are generated in order",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the sequence")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the sequence already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchSequenceConfig(BaseModel):
    """Fetch a single sequence's definition."""

    operation: Literal["fetch_sequence"] = Field(
        "fetch_sequence",
        json_schema_extra={
            "const": "fetch_sequence", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "Fetch Sequence",
        },
        title="Fetch Sequence",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Sequence", description="The sequence to fetch")


class SnowflakeDeleteSequenceConfig(BaseModel):
    """Drop a sequence."""

    operation: Literal["delete_sequence"] = Field(
        "delete_sequence",
        json_schema_extra={
            "const": "delete_sequence", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "Delete Sequence",
        },
        title="Delete Sequence",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Sequence", description="The sequence to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the sequence is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneSequenceConfig(BaseModel):
    """Clone a sequence into a (possibly different) schema."""

    operation: Literal["clone_sequence"] = Field(
        "clone_sequence",
        json_schema_extra={
            "const": "clone_sequence", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "Clone Sequence",
        },
        title="Clone Sequence",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Sequence", description="The sequence to clone")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeRenameSequenceConfig(BaseModel):
    """Rename a sequence to a new identifier."""

    operation: Literal["rename_sequence"] = Field(
        "rename_sequence",
        json_schema_extra={
            "const": "rename_sequence", "ui:hidden": True, "x-category": "Sequences",
            "x-is-trigger": False, "x-display-name": "Rename Sequence",
        },
        title="Rename Sequence",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Sequence", description="The sequence to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed sequence")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the sequence is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_sequences(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/sequences"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_sequences")


async def _create_sequence(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/sequences"
    body = {"name": c.name, "start": _sf_int(c.start), "increment": _sf_int(c.increment),
            "ordered": _sf_bool(c.ordered), "comment": c.comment}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_sequence")


async def _fetch_sequence(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/sequences/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_sequence")


async def _delete_sequence(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/sequences/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_sequence")


async def _clone_sequence(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/sequences/{c.name}:clone"
    params = {"createMode": c.create_mode, "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    body = {"name": c.name}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_sequence")


async def _rename_sequence(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/sequences/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_sequence")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListSequencesConfig,
    SnowflakeCreateSequenceConfig,
    SnowflakeFetchSequenceConfig,
    SnowflakeDeleteSequenceConfig,
    SnowflakeCloneSequenceConfig,
    SnowflakeRenameSequenceConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_sequences": _list_sequences,
    "create_sequence": _create_sequence,
    "fetch_sequence": _fetch_sequence,
    "delete_sequence": _delete_sequence,
    "clone_sequence": _clone_sequence,
    "rename_sequence": _rename_sequence,
})


# ---- service.py ----
class SnowflakeListServicesConfig(BaseModel):
    """List services in a schema."""

    operation: Literal["list_services"] = Field(
        "list_services",
        json_schema_extra={
            "const": "list_services", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Services",
        },
        title="List Services",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateServiceConfig(BaseModel):
    """Create a service in a schema."""

    operation: Literal["create_service"] = Field(
        "create_service",
        json_schema_extra={
            "const": "create_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Create Service",
        },
        title="Create Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the service to create")
    compute_pool: str = Field(..., title="Compute Pool", description="Name of the compute pool on which to run the service")
    spec_type: Optional[str] = Field(
        None, title="Spec Type", description="Source of the service specification",
        json_schema_extra={
            "enum": ["from_file", "from_inline"],
            "enumNames": ["From stage file", "From inline text"],
            "x-enum-searchable": True},
    )
    stage: Optional[str] = Field(None, title="Stage", description="Internal stage holding the spec file (for 'From stage file')")
    spec_file: Optional[str] = Field(None, title="Spec File", description="Path to the spec file on the stage (for 'From stage file')")
    spec_text: Optional[str] = Field(None, title="Spec Text", description="Inline service specification (for 'From inline text')")
    query_warehouse: Optional[str] = Field(None, title="Query Warehouse", description="Default warehouse for service container queries")
    external_access_integrations: Optional[str] = Field(None, title="External Access Integrations", description="Comma-separated list of external access integration names")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the service")
    auto_resume: Optional[str] = Field(
        None, title="Auto Resume", description="Automatically resume the service when called",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    min_instances: Optional[str] = Field(None, title="Min Instances", description="Minimum number of service instances to run")
    max_instances: Optional[str] = Field(None, title="Max Instances", description="Maximum number of service instances to run")
    min_ready_instances: Optional[str] = Field(None, title="Min Ready Instances", description="Minimum ready instances before the service is READY")
    auto_suspend_secs: Optional[str] = Field(None, title="Auto Suspend Seconds", description="Seconds of inactivity before auto-suspend (0 disables)")
    is_async_job: Optional[str] = Field(
        None, title="Async Job", description="Whether the service is an async job service",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the service already exists",
        json_schema_extra={"enum": ["errorIfExists", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeExecuteJobServiceConfig(BaseModel):
    """Create and execute a job service."""

    operation: Literal["execute_job_service"] = Field(
        "execute_job_service",
        json_schema_extra={
            "const": "execute_job_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Execute Job Service",
        },
        title="Execute Job Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the job service")
    compute_pool: str = Field(..., title="Compute Pool", description="Name of the compute pool on which to run the job")
    spec_type: Optional[str] = Field(
        None, title="Spec Type", description="Source of the service specification",
        json_schema_extra={
            "enum": ["from_file", "from_inline"],
            "enumNames": ["From stage file", "From inline text"],
            "x-enum-searchable": True},
    )
    stage: Optional[str] = Field(None, title="Stage", description="Internal stage holding the spec file (for 'From stage file')")
    spec_file: Optional[str] = Field(None, title="Spec File", description="Path to the spec file on the stage (for 'From stage file')")
    spec_text: Optional[str] = Field(None, title="Spec Text", description="Inline service specification (for 'From inline text')")
    query_warehouse: Optional[str] = Field(None, title="Query Warehouse", description="Default warehouse for service container queries")
    external_access_integrations: Optional[str] = Field(None, title="External Access Integrations", description="Comma-separated list of external access integration names")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the job service")
    is_async_job: Optional[str] = Field(
        None, title="Async Job", description="Whether the job service runs asynchronously",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchServiceConfig(BaseModel):
    """Fetch a single service's definition."""

    operation: Literal["fetch_service"] = Field(
        "fetch_service",
        json_schema_extra={
            "const": "fetch_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Fetch Service",
        },
        title="Fetch Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to fetch")


class SnowflakeCreateOrAlterServiceConfig(BaseModel):
    """Create a service, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_service"] = Field(
        "create_or_alter_service",
        json_schema_extra={
            "const": "create_or_alter_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Create or Alter Service",
        },
        title="Create or Alter Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the service")
    compute_pool: str = Field(..., title="Compute Pool", description="Name of the compute pool on which to run the service")
    spec_type: Optional[str] = Field(
        None, title="Spec Type", description="Source of the service specification",
        json_schema_extra={
            "enum": ["from_file", "from_inline"],
            "enumNames": ["From stage file", "From inline text"],
            "x-enum-searchable": True},
    )
    stage: Optional[str] = Field(None, title="Stage", description="Internal stage holding the spec file (for 'From stage file')")
    spec_file: Optional[str] = Field(None, title="Spec File", description="Path to the spec file on the stage (for 'From stage file')")
    spec_text: Optional[str] = Field(None, title="Spec Text", description="Inline service specification (for 'From inline text')")
    query_warehouse: Optional[str] = Field(None, title="Query Warehouse", description="Default warehouse for service container queries")
    external_access_integrations: Optional[str] = Field(None, title="External Access Integrations", description="Comma-separated list of external access integration names")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the service")
    auto_resume: Optional[str] = Field(
        None, title="Auto Resume", description="Automatically resume the service when called",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    min_instances: Optional[str] = Field(None, title="Min Instances", description="Minimum number of service instances to run")
    max_instances: Optional[str] = Field(None, title="Max Instances", description="Maximum number of service instances to run")
    min_ready_instances: Optional[str] = Field(None, title="Min Ready Instances", description="Minimum ready instances before the service is READY")
    auto_suspend_secs: Optional[str] = Field(None, title="Auto Suspend Seconds", description="Seconds of inactivity before auto-suspend (0 disables)")
    is_async_job: Optional[str] = Field(
        None, title="Async Job", description="Whether the service is an async job service",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeDeleteServiceConfig(BaseModel):
    """Drop a service."""

    operation: Literal["delete_service"] = Field(
        "delete_service",
        json_schema_extra={
            "const": "delete_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Delete Service",
        },
        title="Delete Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the service is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchServiceLogsConfig(BaseModel):
    """Fetch the logs for a service container instance."""

    operation: Literal["fetch_service_logs"] = Field(
        "fetch_service_logs",
        json_schema_extra={
            "const": "fetch_service_logs", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Fetch Service Logs",
        },
        title="Fetch Service Logs",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to read logs from")
    instance_id: str = Field(..., title="Instance ID", description="ID of the service instance, starting at 0")
    container_name: str = Field(..., title="Container Name", description="Container name from the service specification")
    num_lines: Optional[str] = Field(None, title="Num Lines", description="Number of trailing log lines to retrieve")


class SnowflakeFetchServiceStatusConfig(BaseModel):
    """Fetch the status for a service (deprecated — prefer List Service Containers)."""

    operation: Literal["fetch_service_status"] = Field(
        "fetch_service_status",
        json_schema_extra={
            "const": "fetch_service_status", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Fetch Service Status",
        },
        title="Fetch Service Status",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to check")
    timeout: Optional[str] = Field(None, title="Timeout", description="Seconds to wait for a steady state before returning")


class SnowflakeListServiceContainersConfig(BaseModel):
    """List all containers of a service."""

    operation: Literal["list_service_containers"] = Field(
        "list_service_containers",
        json_schema_extra={
            "const": "list_service_containers", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Service Containers",
        },
        title="List Service Containers",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service whose containers to list")


class SnowflakeListServiceInstancesConfig(BaseModel):
    """List all instances of a service."""

    operation: Literal["list_service_instances"] = Field(
        "list_service_instances",
        json_schema_extra={
            "const": "list_service_instances", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Service Instances",
        },
        title="List Service Instances",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service whose instances to list")


class SnowflakeListServiceRolesConfig(BaseModel):
    """List all service roles of a service."""

    operation: Literal["list_service_roles"] = Field(
        "list_service_roles",
        json_schema_extra={
            "const": "list_service_roles", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Service Roles",
        },
        title="List Service Roles",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service whose roles to list")


class SnowflakeListServiceRoleGrantsOfConfig(BaseModel):
    """List all grants of a service role (who the role is granted to)."""

    operation: Literal["list_service_role_grants_of"] = Field(
        "list_service_role_grants_of",
        json_schema_extra={
            "const": "list_service_role_grants_of", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Service Role Grants Of",
        },
        title="List Service Role Grants Of",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    service: str = Field(..., title="Service", description="The service that contains the service role")
    name: str = Field(..., title="Service Role", description="The service role to inspect")


class SnowflakeListServiceRoleGrantsToConfig(BaseModel):
    """List all grants given to a service role (privileges the role holds)."""

    operation: Literal["list_service_role_grants_to"] = Field(
        "list_service_role_grants_to",
        json_schema_extra={
            "const": "list_service_role_grants_to", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "List Service Role Grants To",
        },
        title="List Service Role Grants To",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    service: str = Field(..., title="Service", description="The service that contains the service role")
    name: str = Field(..., title="Service Role", description="The service role to inspect")


class SnowflakeResumeServiceConfig(BaseModel):
    """Resume a suspended service."""

    operation: Literal["resume_service"] = Field(
        "resume_service",
        json_schema_extra={
            "const": "resume_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Resume Service",
        },
        title="Resume Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to resume")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the service is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSuspendServiceConfig(BaseModel):
    """Suspend a running service."""

    operation: Literal["suspend_service"] = Field(
        "suspend_service",
        json_schema_extra={
            "const": "suspend_service", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Suspend Service",
        },
        title="Suspend Service",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service to suspend")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the service is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeShowServiceEndpointsConfig(BaseModel):
    """List the endpoints exposed by a service."""

    operation: Literal["show_service_endpoints"] = Field(
        "show_service_endpoints",
        json_schema_extra={
            "const": "show_service_endpoints", "ui:hidden": True, "x-category": "Services",
            "x-is-trigger": False, "x-display-name": "Show Service Endpoints",
        },
        title="Show Service Endpoints",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Service", description="The service whose endpoints to list")


def _sf_service_spec(c):
    spec = {"spec_type": c.spec_type, "stage": c.stage, "spec_file": c.spec_file, "spec_text": c.spec_text}
    spec = {k: v for k, v in spec.items() if v is not None}
    return spec or None


def _sf_eai(c):
    if not c.external_access_integrations:
        return None
    items = [s.strip() for s in c.external_access_integrations.split(",") if s.strip()]
    return items or None


async def _list_services(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/services"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_services")


async def _create_service(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/services"
    body = {"name": c.name, "compute_pool": c.compute_pool, "spec": _sf_service_spec(c),
            "query_warehouse": c.query_warehouse, "external_access_integrations": _sf_eai(c),
            "comment": c.comment, "auto_resume": _sf_bool(c.auto_resume),
            "min_instances": _sf_int(c.min_instances), "max_instances": _sf_int(c.max_instances),
            "min_ready_instances": _sf_int(c.min_ready_instances),
            "auto_suspend_secs": _sf_int(c.auto_suspend_secs), "is_async_job": _sf_bool(c.is_async_job)}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_service")


async def _execute_job_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services:execute-job"
    body = {"name": c.name, "compute_pool": c.compute_pool, "spec": _sf_service_spec(c),
            "query_warehouse": c.query_warehouse, "external_access_integrations": _sf_eai(c),
            "comment": c.comment, "is_async_job": _sf_bool(c.is_async_job)}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="execute_job_service")


async def _fetch_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_service")


async def _create_or_alter_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}"
    body = {"name": c.name, "compute_pool": c.compute_pool, "spec": _sf_service_spec(c),
            "query_warehouse": c.query_warehouse, "external_access_integrations": _sf_eai(c),
            "comment": c.comment, "auto_resume": _sf_bool(c.auto_resume),
            "min_instances": _sf_int(c.min_instances), "max_instances": _sf_int(c.max_instances),
            "min_ready_instances": _sf_int(c.min_ready_instances),
            "auto_suspend_secs": _sf_int(c.auto_suspend_secs), "is_async_job": _sf_bool(c.is_async_job)}
    return await node._request(account, token, "PUT", ep, json_body=body, action_name="create_or_alter_service")


async def _delete_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_service")


async def _fetch_service_logs(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/logs"
    params = {"instanceId": _sf_int(c.instance_id), "containerName": c.container_name, "numLines": _sf_int(c.num_lines)}
    return await node._request(account, token, "GET", ep, params=params, action_name="fetch_service_logs")


async def _fetch_service_status(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/status"
    params = {"timeout": _sf_int(c.timeout)}
    return await node._request(account, token, "GET", ep, params=params, action_name="fetch_service_status")


async def _list_service_containers(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/containers"
    return await node._request(account, token, "GET", ep, action_name="list_service_containers")


async def _list_service_instances(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/instances"
    return await node._request(account, token, "GET", ep, action_name="list_service_instances")


async def _list_service_roles(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/roles"
    return await node._request(account, token, "GET", ep, action_name="list_service_roles")


async def _list_service_role_grants_of(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.service}/roles/{c.name}/grants-of"
    return await node._request(account, token, "GET", ep, action_name="list_service_role_grants_of")


async def _list_service_role_grants_to(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.service}/roles/{c.name}/grants"
    return await node._request(account, token, "GET", ep, action_name="list_service_role_grants_to")


async def _resume_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}:resume"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_service")


async def _suspend_service(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}:suspend"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_service")


async def _show_service_endpoints(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/services/{c.name}/endpoints"
    return await node._request(account, token, "GET", ep, action_name="show_service_endpoints")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListServicesConfig,
    SnowflakeCreateServiceConfig,
    SnowflakeExecuteJobServiceConfig,
    SnowflakeFetchServiceConfig,
    SnowflakeCreateOrAlterServiceConfig,
    SnowflakeDeleteServiceConfig,
    SnowflakeFetchServiceLogsConfig,
    SnowflakeFetchServiceStatusConfig,
    SnowflakeListServiceContainersConfig,
    SnowflakeListServiceInstancesConfig,
    SnowflakeListServiceRolesConfig,
    SnowflakeListServiceRoleGrantsOfConfig,
    SnowflakeListServiceRoleGrantsToConfig,
    SnowflakeResumeServiceConfig,
    SnowflakeSuspendServiceConfig,
    SnowflakeShowServiceEndpointsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_services": _list_services,
    "create_service": _create_service,
    "execute_job_service": _execute_job_service,
    "fetch_service": _fetch_service,
    "create_or_alter_service": _create_or_alter_service,
    "delete_service": _delete_service,
    "fetch_service_logs": _fetch_service_logs,
    "fetch_service_status": _fetch_service_status,
    "list_service_containers": _list_service_containers,
    "list_service_instances": _list_service_instances,
    "list_service_roles": _list_service_roles,
    "list_service_role_grants_of": _list_service_role_grants_of,
    "list_service_role_grants_to": _list_service_role_grants_to,
    "resume_service": _resume_service,
    "suspend_service": _suspend_service,
    "show_service_endpoints": _show_service_endpoints,
})


# ---- stage.py ----
class SnowflakeCreateStageConfig(BaseModel):
    """Create a stage in a schema."""

    operation: Literal["create_stage"] = Field(
        "create_stage",
        json_schema_extra={
            "const": "create_stage", "ui:hidden": True, "x-category": "Stages",
            "x-is-trigger": False, "x-display-name": "Create Stage",
        },
        title="Create Stage",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the stage to create")
    kind: Optional[str] = Field(
        None, title="Kind", description="Whether the stage is permanent or temporary",
        json_schema_extra={"enum": ["PERMANENT", "TEMPORARY"], "x-enum-searchable": True},
    )
    url: Optional[str] = Field(None, title="URL", description="URL for the external stage; blank for an internal stage")
    endpoint: Optional[str] = Field(None, title="Endpoint", description="The S3-compatible API endpoint associated with the stage")
    storage_integration: Optional[str] = Field(None, title="Storage Integration", description="Storage integration associated with the stage")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the stage")
    credentials: Optional[str] = Field(
        None, title="Credentials",
        description="JSON object of stage credentials, e.g. {\"credential_type\":\"AWS\",\"aws_key_id\":\"...\",\"aws_secret_key\":\"...\"}",
    )
    encryption: Optional[str] = Field(
        None, title="Encryption",
        description="JSON object of encryption parameters, e.g. {\"type\":\"AWS_SSE_KMS\",\"kms_key_id\":\"...\"}",
    )
    directory_table: Optional[str] = Field(
        None, title="Directory Table",
        description="JSON object of directory table parameters, e.g. {\"enable\":true,\"auto_refresh\":false}",
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the stage already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchStageConfig(BaseModel):
    """Fetch a single stage's definition."""

    operation: Literal["fetch_stage"] = Field(
        "fetch_stage",
        json_schema_extra={
            "const": "fetch_stage", "ui:hidden": True, "x-category": "Stages",
            "x-is-trigger": False, "x-display-name": "Fetch Stage",
        },
        title="Fetch Stage",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stage", description="The stage to fetch")


class SnowflakeDeleteStageConfig(BaseModel):
    """Drop a stage."""

    operation: Literal["delete_stage"] = Field(
        "delete_stage",
        json_schema_extra={
            "const": "delete_stage", "ui:hidden": True, "x-category": "Stages",
            "x-is-trigger": False, "x-display-name": "Delete Stage",
        },
        title="Delete Stage",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stage", description="The stage to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the stage is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeListFilesConfig(BaseModel):
    """List files in a stage (equivalent to LIST @stage)."""

    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "const": "list_files", "ui:hidden": True, "x-category": "Stages",
            "x-is-trigger": False, "x-display-name": "List Files",
        },
        title="List Files",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stage", description="The stage to list files from")
    pattern: Optional[str] = Field(None, title="Pattern", description="Regex pattern for filtering files by path")


class SnowflakeGetPresignedUrlConfig(BaseModel):
    """Generate a presigned url (and optional encryption materials) for a stage file."""

    operation: Literal["get_presigned_url"] = Field(
        "get_presigned_url",
        json_schema_extra={
            "const": "get_presigned_url", "ui:hidden": True, "x-category": "Stages",
            "x-is-trigger": False, "x-display-name": "Get Presigned URL",
        },
        title="Get Presigned URL",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stage", description="The stage containing the file")
    file_path: str = Field(..., title="File Path", description="The full stage path of the file")
    expiration_time: Optional[str] = Field(None, title="Expiration Time", description="Expiration time of the generated presigned url in seconds")


async def _create_stage(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/stages"
    body = {"name": c.name, "kind": c.kind, "url": c.url, "endpoint": c.endpoint,
            "storage_integration": c.storage_integration, "comment": c.comment,
            "credentials": c.credentials, "encryption": c.encryption,
            "directory_table": c.directory_table}
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_stage")


async def _fetch_stage(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/stages/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_stage")


async def _delete_stage(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/stages/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_stage")


async def _list_files(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/stages/{c.name}/files"
    params = {"pattern": c.pattern}
    return await node._request(account, token, "GET", ep, params=params, action_name="list_files")


async def _get_presigned_url(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/stages/{c.name}/files/{c.file_path}:presigned-url"
    body = {"expiration_time": _sf_int(c.expiration_time)}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="get_presigned_url")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeCreateStageConfig,
    SnowflakeFetchStageConfig,
    SnowflakeDeleteStageConfig,
    SnowflakeListFilesConfig,
    SnowflakeGetPresignedUrlConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "create_stage": _create_stage,
    "fetch_stage": _fetch_stage,
    "delete_stage": _delete_stage,
    "list_files": _list_files,
    "get_presigned_url": _get_presigned_url,
})


# ---- stream.py ----
class SnowflakeListStreamsConfig(BaseModel):
    """List streams in a schema."""

    operation: Literal["list_streams"] = Field(
        "list_streams",
        json_schema_extra={
            "const": "list_streams", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "List Streams",
        },
        title="List Streams",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateStreamConfig(BaseModel):
    """Create a stream on a table, external table, view, or stage."""

    operation: Literal["create_stream"] = Field(
        "create_stream",
        json_schema_extra={
            "const": "create_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Create Stream",
        },
        title="Create Stream",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the stream to create")
    source_type: str = Field(
        ..., title="Source Type", description="Type of the source object the stream tracks",
        json_schema_extra={"enum": ["table", "external_table", "view", "stage"], "x-enum-searchable": True},
    )
    source_name: str = Field(..., title="Source Name", description="Name of the source whose changes are tracked")
    source_database_name: Optional[str] = Field(None, title="Source Database", description="Database of the source (defaults to path database)")
    source_schema_name: Optional[str] = Field(None, title="Source Schema", description="Schema of the source (defaults to path schema)")
    append_only: Optional[str] = Field(
        None, title="Append Only", description="Track only row inserts (table/view sources)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    insert_only: Optional[str] = Field(
        None, title="Insert Only", description="Track only inserts (external table sources)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    show_initial_rows: Optional[str] = Field(
        None, title="Show Initial Rows", description="Show initial rows on first consumption (table/view sources)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    point_of_time_type: Optional[str] = Field(
        None, title="Point of Time Type", description="Time-travel reference type for the stream offset",
        json_schema_extra={"enum": ["timestamp", "offset", "statement", "stream"], "x-enum-searchable": True},
    )
    point_of_time_reference: Optional[str] = Field(
        None, title="Point of Time Reference", description="Relation to the point of time",
        json_schema_extra={"enum": ["at", "before"], "x-enum-searchable": True},
    )
    point_of_time_value: Optional[str] = Field(None, title="Point of Time Value", description="Timestamp/offset/statement id/stream name for the chosen type")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the stream")
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Retain access privileges when replacing the stream",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the stream already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchStreamConfig(BaseModel):
    """Fetch a single stream's definition."""

    operation: Literal["fetch_stream"] = Field(
        "fetch_stream",
        json_schema_extra={
            "const": "fetch_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Fetch Stream",
        },
        title="Fetch Stream",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stream", description="The stream to fetch")


class SnowflakeDeleteStreamConfig(BaseModel):
    """Drop a stream."""

    operation: Literal["delete_stream"] = Field(
        "delete_stream",
        json_schema_extra={
            "const": "delete_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Delete Stream",
        },
        title="Delete Stream",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stream", description="The stream to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the stream is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneStreamConfig(BaseModel):
    """Clone a stream into a (possibly different) schema."""

    operation: Literal["clone_stream"] = Field(
        "clone_stream",
        json_schema_extra={
            "const": "clone_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Clone Stream",
        },
        title="Clone Stream",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Stream", description="The stream to clone")
    clone_name: str = Field(..., title="Clone Name", description="Name of the cloned stream")
    target_database: str = Field(..., title="Target Database", description="Database of the cloned stream")
    target_schema: str = Field(..., title="Target Schema", description="Schema of the cloned stream")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the cloned stream")
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Retain access privileges on the clone",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsStreamConfig(BaseModel):
    """Set a tag on a stream."""

    operation: Literal["set_tags_stream"] = Field(
        "set_tags_stream",
        json_schema_extra={
            "const": "set_tags_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Set Stream Tags",
        },
        title="Set Stream Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stream", description="The stream to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the stream is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsStreamConfig(BaseModel):
    """Unset a tag from a stream."""

    operation: Literal["unset_tags_stream"] = Field(
        "unset_tags_stream",
        json_schema_extra={
            "const": "unset_tags_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Unset Stream Tags",
        },
        title="Unset Stream Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stream", description="The stream to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the stream is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsStreamConfig(BaseModel):
    """Get the tag assignments for a stream (requires an active warehouse)."""

    operation: Literal["get_tags_stream"] = Field(
        "get_tags_stream",
        json_schema_extra={
            "const": "get_tags_stream", "ui:hidden": True, "x-category": "Streams",
            "x-is-trigger": False, "x-display-name": "Get Stream Tags",
        },
        title="Get Stream Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Stream", description="The stream to read tags from")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_streams(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/streams"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_streams")


async def _create_stream(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/streams"
    source = {"src_type": c.source_type, "name": c.source_name,
              "database_name": c.source_database_name, "schema_name": c.source_schema_name,
              "append_only": _sf_bool(c.append_only), "insert_only": _sf_bool(c.insert_only),
              "show_initial_rows": _sf_bool(c.show_initial_rows)}
    if c.point_of_time_type:
        pot = {"point_of_time_type": c.point_of_time_type, "reference": c.point_of_time_reference}
        if c.point_of_time_value:
            pot[c.point_of_time_type] = c.point_of_time_value
        source["point_of_time"] = {k: v for k, v in pot.items() if v is not None}
    source = {k: v for k, v in source.items() if v is not None}
    body = {"name": c.name, "stream_source": source, "comment": c.comment}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_stream")


async def _fetch_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_stream")


async def _delete_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_stream")


async def _clone_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}:clone"
    params = {"createMode": c.create_mode, "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "copyGrants": _sf_bool(c.copy_grants)}
    body = {"name": c.clone_name, "comment": c.comment}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_stream")


async def _set_tags_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_stream")


async def _unset_tags_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_stream")


async def _get_tags_stream(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streams/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_stream")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListStreamsConfig,
    SnowflakeCreateStreamConfig,
    SnowflakeFetchStreamConfig,
    SnowflakeDeleteStreamConfig,
    SnowflakeCloneStreamConfig,
    SnowflakeSetTagsStreamConfig,
    SnowflakeUnsetTagsStreamConfig,
    SnowflakeGetTagsStreamConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_streams": _list_streams,
    "create_stream": _create_stream,
    "fetch_stream": _fetch_stream,
    "delete_stream": _delete_stream,
    "clone_stream": _clone_stream,
    "set_tags_stream": _set_tags_stream,
    "unset_tags_stream": _unset_tags_stream,
    "get_tags_stream": _get_tags_stream,
})


# ---- streamlit.py ----
class SnowflakeListStreamlitsConfig(BaseModel):
    """List Streamlits in a schema."""

    operation: Literal["list_streamlits"] = Field(
        "list_streamlits",
        json_schema_extra={
            "const": "list_streamlits", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "List Streamlits",
        },
        title="List Streamlits",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")


class SnowflakeCreateStreamlitConfig(BaseModel):
    """Create a Streamlit application, or replace an existing one."""

    operation: Literal["create_streamlit"] = Field(
        "create_streamlit",
        json_schema_extra={
            "const": "create_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Create Streamlit",
        },
        title="Create Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the Streamlit to create")
    title_: Optional[str] = Field(None, title="Title", description="User-facing title of the Streamlit app")
    comment: Optional[str] = Field(None, title="Comment", description="Optional description of the app")
    main_file: Optional[str] = Field(None, title="Main File", description="Name and path of the entry file for the app")
    query_warehouse: Optional[str] = Field(None, title="Query Warehouse", description="Warehouse used to run queries issued by the app")
    default_version: Optional[str] = Field(None, title="Default Version", description="Default version name (e.g. 'first', 'last', 'version$1')")
    source_location: Optional[str] = Field(None, title="Source Location", description="Stage from which source files are copied to initialize the app")
    imports: Optional[str] = Field(None, title="Imports", description="Comma-separated list of files to import from a stage")
    external_access_integrations: Optional[str] = Field(None, title="External Access Integrations", description="Comma-separated external access integrations for the app")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the Streamlit already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchStreamlitConfig(BaseModel):
    """Fetch a single Streamlit's details."""

    operation: Literal["fetch_streamlit"] = Field(
        "fetch_streamlit",
        json_schema_extra={
            "const": "fetch_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Fetch Streamlit",
        },
        title="Fetch Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to fetch")


class SnowflakeDeleteStreamlitConfig(BaseModel):
    """Delete a Streamlit (restorable via undrop within the retention period)."""

    operation: Literal["delete_streamlit"] = Field(
        "delete_streamlit",
        json_schema_extra={
            "const": "delete_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Delete Streamlit",
        },
        title="Delete Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to delete")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the Streamlit is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropStreamlitConfig(BaseModel):
    """Restore a previously deleted Streamlit within the retention period."""

    operation: Literal["undrop_streamlit"] = Field(
        "undrop_streamlit",
        json_schema_extra={
            "const": "undrop_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Undrop Streamlit",
        },
        title="Undrop Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to restore")


class SnowflakeRenameStreamlitConfig(BaseModel):
    """Rename a Streamlit, optionally into a different database or schema."""

    operation: Literal["rename_streamlit"] = Field(
        "rename_streamlit",
        json_schema_extra={
            "const": "rename_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Rename Streamlit",
        },
        title="Rename Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Streamlit", description="The Streamlit to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed Streamlit")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the Streamlit is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeAddLiveVersionStreamlitConfig(BaseModel):
    """Add a live version to a Streamlit, making a version active for users."""

    operation: Literal["add_live_version_streamlit"] = Field(
        "add_live_version_streamlit",
        json_schema_extra={
            "const": "add_live_version_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Add Live Version",
        },
        title="Add Live Version",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to update")
    from_last: Optional[str] = Field(
        None, title="From Last", description="Set the LIVE version to the LAST version of the Streamlit",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    version_name: Optional[str] = Field(None, title="Version Alias", description="Optional alias name for the live version")
    version_comment: Optional[str] = Field(None, title="Version Comment", description="Optional comment for the live version")


class SnowflakeCommitStreamlitConfig(BaseModel):
    """Commit the LIVE version of a Streamlit to its connected Git repository."""

    operation: Literal["commit_streamlit"] = Field(
        "commit_streamlit",
        json_schema_extra={
            "const": "commit_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Commit Live Version",
        },
        title="Commit Live Version",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to commit")
    version_comment: Optional[str] = Field(None, title="Commit Message", description="Optional commit message")


class SnowflakeAddVersionStreamlitConfig(BaseModel):
    """Add a new version to a Streamlit by copying files from a stage location."""

    operation: Literal["add_version_streamlit"] = Field(
        "add_version_streamlit",
        json_schema_extra={
            "const": "add_version_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Add Version From Source",
        },
        title="Add Version From Source",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to update")
    source_location: str = Field(..., title="Source Location", description="URI to the source location")
    version_name: str = Field(..., title="Version Name", description="Name/alias for the new version")
    version_comment: Optional[str] = Field(None, title="Version Comment", description="Optional comment for the new version")
    version_if_not_exists: Optional[str] = Field(
        None, title="If Not Exists", description="Do not error if the version already exists",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeAddVersionFromGitStreamlitConfig(BaseModel):
    """Add a new version to a Streamlit using a Git tag or commit reference URI."""

    operation: Literal["add_version_from_git_streamlit"] = Field(
        "add_version_from_git_streamlit",
        json_schema_extra={
            "const": "add_version_from_git_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Add Version From Git",
        },
        title="Add Version From Git",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to update")
    git_ref: str = Field(..., title="Git Ref", description="Git reference URI (tag URI or commit URI)")
    version_name: str = Field(..., title="Version Name", description="Name or alias for the new version")
    version_comment: Optional[str] = Field(None, title="Version Comment", description="Optional comment associated with the pull")


class SnowflakeAbortStreamlitConfig(BaseModel):
    """Abort the live version of a Streamlit, discarding uncommitted changes."""

    operation: Literal["abort_streamlit"] = Field(
        "abort_streamlit",
        json_schema_extra={
            "const": "abort_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Abort Live Version",
        },
        title="Abort Live Version",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to abort")


class SnowflakePullStreamlitConfig(BaseModel):
    """Pull the latest changes from the Git repository for a Streamlit."""

    operation: Literal["pull_streamlit"] = Field(
        "pull_streamlit",
        json_schema_extra={
            "const": "pull_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Pull From Git",
        },
        title="Pull From Git",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to pull")


class SnowflakePushStreamlitConfig(BaseModel):
    """Push committed changes from a Streamlit back to its Git repository."""

    operation: Literal["push_streamlit"] = Field(
        "push_streamlit",
        json_schema_extra={
            "const": "push_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Push To Git",
        },
        title="Push To Git",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to push")
    auth_type: str = Field(
        ..., title="Auth Type", description="Authentication method for the Git push",
        json_schema_extra={"enum": ["CREDENTIALS", "USERNAME_PASSWORD"], "x-enum-searchable": True},
    )
    git_author_name: str = Field(..., title="Git Author Name", description="The name of the Git author")
    git_author_email: str = Field(..., title="Git Author Email", description="The email of the Git author")
    git_credentials: Optional[str] = Field(None, title="Git Credentials", description="Snowflake secret with credentials (CREDENTIALS auth)")
    git_username: Optional[str] = Field(None, title="Git Username", description="A Git username (USERNAME_PASSWORD auth)")
    git_password: Optional[str] = Field(None, title="Git Password", description="A Git password (USERNAME_PASSWORD auth)")
    to_git_branch_uri: Optional[str] = Field(None, title="To Git Branch URI", description="Push committed changes to this branch")
    git_push_comment: Optional[str] = Field(None, title="Push Comment", description="A comment to include in the Git push")


class SnowflakeSetTagsStreamlitConfig(BaseModel):
    """Set a tag on a Streamlit."""

    operation: Literal["set_tags_streamlit"] = Field(
        "set_tags_streamlit",
        json_schema_extra={
            "const": "set_tags_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Set Tags on Streamlit",
        },
        title="Set Tags on Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the Streamlit is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsStreamlitConfig(BaseModel):
    """Unset a tag from a Streamlit."""

    operation: Literal["unset_tags_streamlit"] = Field(
        "unset_tags_streamlit",
        json_schema_extra={
            "const": "unset_tags_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Unset Tags from Streamlit",
        },
        title="Unset Tags from Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the Streamlit is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsStreamlitConfig(BaseModel):
    """Get the tag assignments for a Streamlit."""

    operation: Literal["get_tags_streamlit"] = Field(
        "get_tags_streamlit",
        json_schema_extra={
            "const": "get_tags_streamlit", "ui:hidden": True, "x-category": "Streamlit Apps",
            "x-is-trigger": False, "x-display-name": "Get Tags on Streamlit",
        },
        title="Get Tags on Streamlit",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Streamlit", description="The Streamlit whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_streamlit_csv(value):
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


async def _list_streamlits(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit, "fromName": c.from_name}
    return await node._request(account, token, "GET", base, params=params, action_name="list_streamlits")


async def _create_streamlit(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits"
    body = {
        "name": c.name, "title": c.title_, "comment": c.comment, "main_file": c.main_file,
        "query_warehouse": c.query_warehouse, "default_version": c.default_version,
        "source_location": c.source_location, "imports": _sf_streamlit_csv(c.imports),
        "external_access_integrations": _sf_streamlit_csv(c.external_access_integrations),
    }
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_streamlit")


async def _fetch_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_streamlit")


async def _delete_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_streamlit")


async def _undrop_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_streamlit")


async def _rename_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_streamlit")


async def _add_live_version_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:add-live-version"
    params = {"fromLast": _sf_bool(c.from_last)}
    body = {"version": {"name": c.version_name, "comment": c.version_comment}}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="add_live_version_streamlit")


async def _commit_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:commit"
    body = {"version": {"comment": c.version_comment}}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="commit_streamlit")


async def _add_version_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:add-version"
    body = {
        "source_location": c.source_location,
        "version": {"name": c.version_name, "comment": c.version_comment,
                    "ifNotExists": _sf_bool(c.version_if_not_exists)},
    }
    return await node._request(account, token, "POST", ep, json_body=body, action_name="add_version_streamlit")


async def _add_version_from_git_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:add-version-from-git"
    body = {
        "git_ref": c.git_ref,
        "version": {"name": c.version_name, "comment": c.version_comment},
    }
    return await node._request(account, token, "POST", ep, json_body=body, action_name="add_version_from_git_streamlit")


async def _abort_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:abort"
    return await node._request(account, token, "POST", ep, action_name="abort_streamlit")


async def _pull_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:pull"
    return await node._request(account, token, "POST", ep, action_name="pull_streamlit")


async def _push_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:push"
    body = {
        "auth_type": c.auth_type, "git_author_name": c.git_author_name,
        "git_author_email": c.git_author_email, "git_credentials": c.git_credentials,
        "git_username": c.git_username, "git_password": c.git_password,
        "to_git_branch_uri": c.to_git_branch_uri, "git_push_comment": c.git_push_comment,
    }
    return await node._request(account, token, "POST", ep, json_body=body, action_name="push_streamlit")


async def _set_tags_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_streamlit")


async def _unset_tags_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_streamlit")


async def _get_tags_streamlit(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/streamlits/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_streamlit")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListStreamlitsConfig,
    SnowflakeCreateStreamlitConfig,
    SnowflakeFetchStreamlitConfig,
    SnowflakeDeleteStreamlitConfig,
    SnowflakeUndropStreamlitConfig,
    SnowflakeRenameStreamlitConfig,
    SnowflakeAddLiveVersionStreamlitConfig,
    SnowflakeCommitStreamlitConfig,
    SnowflakeAddVersionStreamlitConfig,
    SnowflakeAddVersionFromGitStreamlitConfig,
    SnowflakeAbortStreamlitConfig,
    SnowflakePullStreamlitConfig,
    SnowflakePushStreamlitConfig,
    SnowflakeSetTagsStreamlitConfig,
    SnowflakeUnsetTagsStreamlitConfig,
    SnowflakeGetTagsStreamlitConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_streamlits": _list_streamlits,
    "create_streamlit": _create_streamlit,
    "fetch_streamlit": _fetch_streamlit,
    "delete_streamlit": _delete_streamlit,
    "undrop_streamlit": _undrop_streamlit,
    "rename_streamlit": _rename_streamlit,
    "add_live_version_streamlit": _add_live_version_streamlit,
    "commit_streamlit": _commit_streamlit,
    "add_version_streamlit": _add_version_streamlit,
    "add_version_from_git_streamlit": _add_version_from_git_streamlit,
    "abort_streamlit": _abort_streamlit,
    "pull_streamlit": _pull_streamlit,
    "push_streamlit": _push_streamlit,
    "set_tags_streamlit": _set_tags_streamlit,
    "unset_tags_streamlit": _unset_tags_streamlit,
    "get_tags_streamlit": _get_tags_streamlit,
})


# ---- table.py ----
class SnowflakeCreateTableConfig(BaseModel):
    """Create a table in a schema."""

    operation: Literal["create_table"] = Field(
        "create_table",
        json_schema_extra={
            "const": "create_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table",
        },
        title="Create Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table to create")
    kind: Optional[str] = Field(
        None, title="Kind", description="Table type",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT", "TEMPORARY"], "x-enum-searchable": True},
    )
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    enable_schema_evolution: Optional[str] = Field(
        None, title="Enable Schema Evolution", description="Whether schema evolution is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    change_tracking: Optional[str] = Field(
        None, title="Change Tracking", description="Whether change tracking is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention (days)", description="Time Travel retention period")
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension (days)", description="Max Time Travel extension period")
    default_ddl_collation: Optional[str] = Field(None, title="Default DDL Collation", description="Default collation for columns")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    columns: Optional[str] = Field(
        None, title="Columns",
        description='JSON array of column definitions, e.g. [{"name": "id", "datatype": "NUMBER"}, {"name": "email", "datatype": "TEXT", "comment": "..."}]',
    )
    constraints: Optional[str] = Field(
        None, title="Constraints",
        description='JSON array of table constraints, e.g. [{"name": "pk", "column_names": ["id"], "constraint_type": "PRIMARY KEY"}]',
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableAsSelectConfig(BaseModel):
    """Create a table from the result of a SELECT query."""

    operation: Literal["create_table_as_select"] = Field(
        "create_table_as_select",
        json_schema_extra={
            "const": "create_table_as_select", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table As Select",
        },
        title="Create Table As Select",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table to create")
    query: str = Field(..., title="Query", description="SELECT query that sets up the table values (and possibly columns)")
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    columns: Optional[str] = Field(
        None, title="Columns",
        description='JSON array of column definitions, e.g. [{"name": "id", "datatype": "NUMBER"}]',
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableAsSelectDeprecatedConfig(BaseModel):
    """(Deprecated) Create a table from a SELECT query (name in the path)."""

    operation: Literal["create_table_as_select_deprecated"] = Field(
        "create_table_as_select_deprecated",
        json_schema_extra={
            "const": "create_table_as_select_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table As Select (Deprecated)",
        },
        title="Create Table As Select (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table to create")
    query: str = Field(..., title="Query", description="SELECT query that sets up the table values (and possibly columns)")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableUsingTemplateConfig(BaseModel):
    """Create a table using templates in staged files (INFER_SCHEMA)."""

    operation: Literal["create_table_using_template"] = Field(
        "create_table_using_template",
        json_schema_extra={
            "const": "create_table_using_template", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table Using Template",
        },
        title="Create Table Using Template",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table to create")
    query: str = Field(..., title="Query", description="SQL query using INFER_SCHEMA on staged files to set column definitions")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableUsingTemplateDeprecatedConfig(BaseModel):
    """(Deprecated) Create a table using templates in staged files (name in the path)."""

    operation: Literal["create_table_using_template_deprecated"] = Field(
        "create_table_using_template_deprecated",
        json_schema_extra={
            "const": "create_table_using_template_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table Using Template (Deprecated)",
        },
        title="Create Table Using Template (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table to create")
    query: str = Field(..., title="Query", description="SQL query using INFER_SCHEMA on staged files to set column definitions")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the table already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateOrAlterTableConfig(BaseModel):
    """Create a table, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_table"] = Field(
        "create_or_alter_table",
        json_schema_extra={
            "const": "create_or_alter_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create or Alter Table",
        },
        title="Create or Alter Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the table")
    kind: Optional[str] = Field(
        None, title="Kind", description="Table type",
        json_schema_extra={"enum": ["PERMANENT", "TRANSIENT", "TEMPORARY"], "x-enum-searchable": True},
    )
    cluster_by: Optional[str] = Field(None, title="Cluster By", description="Comma-separated clustering key columns/expressions")
    enable_schema_evolution: Optional[str] = Field(
        None, title="Enable Schema Evolution", description="Whether schema evolution is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    change_tracking: Optional[str] = Field(
        None, title="Change Tracking", description="Whether change tracking is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    data_retention_time_in_days: Optional[str] = Field(None, title="Data Retention (days)", description="Time Travel retention period")
    max_data_extension_time_in_days: Optional[str] = Field(None, title="Max Data Extension (days)", description="Max Time Travel extension period")
    default_ddl_collation: Optional[str] = Field(None, title="Default DDL Collation", description="Default collation for columns")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the table")
    columns: Optional[str] = Field(
        None, title="Columns",
        description='JSON array of column definitions, e.g. [{"name": "id", "datatype": "NUMBER"}]',
    )
    constraints: Optional[str] = Field(
        None, title="Constraints",
        description='JSON array of table constraints, e.g. [{"name": "pk", "column_names": ["id"], "constraint_type": "PRIMARY KEY"}]',
    )


class SnowflakeDeleteTableConfig(BaseModel):
    """Drop a table."""

    operation: Literal["delete_table"] = Field(
        "delete_table",
        json_schema_extra={
            "const": "delete_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Delete Table",
        },
        title="Delete Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCloneTableConfig(BaseModel):
    """Clone a table into a (possibly different) schema."""

    operation: Literal["clone_table"] = Field(
        "clone_table",
        json_schema_extra={
            "const": "clone_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Clone Table",
        },
        title="Clone Table",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Table", description="The source table to clone")
    target_name: str = Field(..., title="New Name", description="Name of the newly created table")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    point_of_time: Optional[str] = Field(
        None, title="Point of Time",
        description='JSON object for Time Travel cloning, e.g. {"point_of_time_type": "timestamp", "timestamp": "..."}',
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableLikeConfig(BaseModel):
    """Create a new empty table like an existing one."""

    operation: Literal["create_table_like"] = Field(
        "create_table_like",
        json_schema_extra={
            "const": "create_table_like", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table Like",
        },
        title="Create Table Like",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Table", description="The source table to model the new one after")
    target_name: str = Field(..., title="New Name", description="Name of the table to be created")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateTableLikeDeprecatedConfig(BaseModel):
    """(Deprecated) Create a new empty table like an existing one."""

    operation: Literal["create_table_like_deprecated"] = Field(
        "create_table_like_deprecated",
        json_schema_extra={
            "const": "create_table_like_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Create Table Like (Deprecated)",
        },
        title="Create Table Like (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Table", description="The source table to model the new one after")
    new_table_name: str = Field(..., title="New Name", description="The name of the table to be created")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode", description="Behavior when the target already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the source table",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropTableConfig(BaseModel):
    """Undrop a previously dropped table."""

    operation: Literal["undrop_table"] = Field(
        "undrop_table",
        json_schema_extra={
            "const": "undrop_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Undrop Table",
        },
        title="Undrop Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to undrop")


class SnowflakeSuspendReclusterTableConfig(BaseModel):
    """Suspend automatic reclustering for a table."""

    operation: Literal["suspend_recluster_table"] = Field(
        "suspend_recluster_table",
        json_schema_extra={
            "const": "suspend_recluster_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Suspend Recluster Table",
        },
        title="Suspend Recluster Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to suspend reclustering for")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSuspendReclusterTableDeprecatedConfig(BaseModel):
    """(Deprecated) Suspend automatic reclustering for a table."""

    operation: Literal["suspend_recluster_table_deprecated"] = Field(
        "suspend_recluster_table_deprecated",
        json_schema_extra={
            "const": "suspend_recluster_table_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Suspend Recluster Table (Deprecated)",
        },
        title="Suspend Recluster Table (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to suspend reclustering for")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeResumeReclusterTableConfig(BaseModel):
    """Resume automatic reclustering for a table."""

    operation: Literal["resume_recluster_table"] = Field(
        "resume_recluster_table",
        json_schema_extra={
            "const": "resume_recluster_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Resume Recluster Table",
        },
        title="Resume Recluster Table",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to resume reclustering for")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeResumeReclusterTableDeprecatedConfig(BaseModel):
    """(Deprecated) Resume automatic reclustering for a table."""

    operation: Literal["resume_recluster_table_deprecated"] = Field(
        "resume_recluster_table_deprecated",
        json_schema_extra={
            "const": "resume_recluster_table_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Resume Recluster Table (Deprecated)",
        },
        title="Resume Recluster Table (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to resume reclustering for")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSwapWithTableConfig(BaseModel):
    """Swap a table's metadata and data with another table."""

    operation: Literal["swap_with_table"] = Field(
        "swap_with_table",
        json_schema_extra={
            "const": "swap_with_table", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Swap With Table",
        },
        title="Swap With Table",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Table", description="The source table to swap")
    target_name: str = Field(..., title="Target Table", description="The name of the target table to be swapped with")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSwapWithTableDeprecatedConfig(BaseModel):
    """(Deprecated) Swap a table with another table (fully-qualified target)."""

    operation: Literal["swap_with_table_deprecated"] = Field(
        "swap_with_table_deprecated",
        json_schema_extra={
            "const": "swap_with_table_deprecated", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Swap With Table (Deprecated)",
        },
        title="Swap With Table (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Table", description="The source table to swap")
    target_table_name: str = Field(..., title="Target Table", description="The fully-specified name of the target table to be swapped with")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTableTagsConfig(BaseModel):
    """Set a tag on a table."""

    operation: Literal["set_table_tags"] = Field(
        "set_table_tags",
        json_schema_extra={
            "const": "set_table_tags", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Set Table Tags",
        },
        title="Set Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to assign")
    tag_value: str = Field(..., title="Tag Value", description="Value of the tag to assign")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTableTagsConfig(BaseModel):
    """Unset a tag from a table."""

    operation: Literal["unset_table_tags"] = Field(
        "unset_table_tags",
        json_schema_extra={
            "const": "unset_table_tags", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Unset Table Tags",
        },
        title="Unset Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the table is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTableTagsConfig(BaseModel):
    """Get the tag assignments for a table (requires an active warehouse)."""

    operation: Literal["get_table_tags"] = Field(
        "get_table_tags",
        json_schema_extra={
            "const": "get_table_tags", "ui:hidden": True, "x-category": "Tables",
            "x-is-trigger": False, "x-display-name": "Get Table Tags",
        },
        title="Get Table Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Table", description="The table whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited through lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_cluster_by(value):
    return [s.strip() for s in value.split(",") if s.strip()] if value else None


async def _create_table(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/tables"
    body = {
        "name": c.name, "kind": c.kind, "cluster_by": _sf_cluster_by(c.cluster_by),
        "enable_schema_evolution": _sf_bool(c.enable_schema_evolution),
        "change_tracking": _sf_bool(c.change_tracking),
        "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
        "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
        "default_ddl_collation": c.default_ddl_collation, "comment": c.comment,
        "columns": _sf_json(c.columns), "constraints": _sf_json(c.constraints),
    }
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_table")


async def _create_table_as_select(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/tables:as-select"
    body = {"name": c.name, "cluster_by": _sf_cluster_by(c.cluster_by), "columns": _sf_json(c.columns)}
    params = {"query": c.query, "createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_table_as_select")


async def _create_table_as_select_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:as_select"
    body = {"name": c.name}
    params = {"query": c.query, "createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="create_table_as_select_deprecated")


async def _create_table_using_template(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/tables:using-template"
    body = {"name": c.name}
    params = {"query": c.query, "createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_table_using_template")


async def _create_table_using_template_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:using_template"
    params = {"query": c.query, "createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", ep, params=params, action_name="create_table_using_template_deprecated")


async def _create_or_alter_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}"
    body = {
        "name": c.name, "kind": c.kind, "cluster_by": _sf_cluster_by(c.cluster_by),
        "enable_schema_evolution": _sf_bool(c.enable_schema_evolution),
        "change_tracking": _sf_bool(c.change_tracking),
        "data_retention_time_in_days": _sf_int(c.data_retention_time_in_days),
        "max_data_extension_time_in_days": _sf_int(c.max_data_extension_time_in_days),
        "default_ddl_collation": c.default_ddl_collation, "comment": c.comment,
        "columns": _sf_json(c.columns), "constraints": _sf_json(c.constraints),
    }
    return await node._request(account, token, "PUT", ep, json_body=body, action_name="create_or_alter_table")


async def _delete_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_table")


async def _clone_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:clone"
    body = {"name": c.target_name, "point_of_time": _sf_json(c.point_of_time)}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants),
              "targetDatabase": c.target_database, "targetSchema": c.target_schema}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="clone_table")


async def _create_table_like(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:create-like"
    body = {"name": c.target_name}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="create_table_like")


async def _create_table_like_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:create_like"
    params = {"newTableName": c.new_table_name, "createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", ep, params=params, action_name="create_table_like_deprecated")


async def _undrop_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_table")


async def _suspend_recluster_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:suspend-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_recluster_table")


async def _suspend_recluster_table_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:suspend_recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="suspend_recluster_table_deprecated")


async def _resume_recluster_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:resume-recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_recluster_table")


async def _resume_recluster_table_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:resume_recluster"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="resume_recluster_table_deprecated")


async def _swap_with_table(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:swap-with"
    params = {"targetName": c.target_name, "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="swap_with_table")


async def _swap_with_table_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:swapwith"
    params = {"targetTableName": c.target_table_name, "ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="swap_with_table_deprecated")


async def _set_table_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:set-tags"
    body = [{"name": c.tag_name, "value": c.tag_value}]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_table_tags")


async def _unset_table_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:unset-tags"
    body = [{"name": c.tag_name}]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_table_tags")


async def _get_table_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_table_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeCreateTableConfig,
    SnowflakeCreateTableAsSelectConfig,
    SnowflakeCreateTableAsSelectDeprecatedConfig,
    SnowflakeCreateTableUsingTemplateConfig,
    SnowflakeCreateTableUsingTemplateDeprecatedConfig,
    SnowflakeCreateOrAlterTableConfig,
    SnowflakeDeleteTableConfig,
    SnowflakeCloneTableConfig,
    SnowflakeCreateTableLikeConfig,
    SnowflakeCreateTableLikeDeprecatedConfig,
    SnowflakeUndropTableConfig,
    SnowflakeSuspendReclusterTableConfig,
    SnowflakeSuspendReclusterTableDeprecatedConfig,
    SnowflakeResumeReclusterTableConfig,
    SnowflakeResumeReclusterTableDeprecatedConfig,
    SnowflakeSwapWithTableConfig,
    SnowflakeSwapWithTableDeprecatedConfig,
    SnowflakeSetTableTagsConfig,
    SnowflakeUnsetTableTagsConfig,
    SnowflakeGetTableTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "create_table": _create_table,
    "create_table_as_select": _create_table_as_select,
    "create_table_as_select_deprecated": _create_table_as_select_deprecated,
    "create_table_using_template": _create_table_using_template,
    "create_table_using_template_deprecated": _create_table_using_template_deprecated,
    "create_or_alter_table": _create_or_alter_table,
    "delete_table": _delete_table,
    "clone_table": _clone_table,
    "create_table_like": _create_table_like,
    "create_table_like_deprecated": _create_table_like_deprecated,
    "undrop_table": _undrop_table,
    "suspend_recluster_table": _suspend_recluster_table,
    "suspend_recluster_table_deprecated": _suspend_recluster_table_deprecated,
    "resume_recluster_table": _resume_recluster_table,
    "resume_recluster_table_deprecated": _resume_recluster_table_deprecated,
    "swap_with_table": _swap_with_table,
    "swap_with_table_deprecated": _swap_with_table_deprecated,
    "set_table_tags": _set_table_tags,
    "unset_table_tags": _unset_table_tags,
    "get_table_tags": _get_table_tags,
})


# ---- tag.py ----
class SnowflakeListTagsConfig(BaseModel):
    """List tags in a schema."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "List Tags",
        },
        title="List Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateTagConfig(BaseModel):
    """Create a tag in a schema."""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={
            "const": "create_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Create Tag",
        },
        title="Create Tag",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the tag to create")
    allowed_values: Optional[str] = Field(None, title="Allowed Values", description="Comma-separated string values the tag may take")
    propagate: Optional[str] = Field(None, title="Propagate", description="Whether the tag propagates from source to target objects")
    on_conflict: Optional[str] = Field(None, title="On Conflict", description="Behavior when propagated tag values conflict")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the tag")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the tag already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )


class SnowflakeFetchTagConfig(BaseModel):
    """Fetch a single tag's definition."""

    operation: Literal["fetch_tag"] = Field(
        "fetch_tag",
        json_schema_extra={
            "const": "fetch_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Fetch Tag",
        },
        title="Fetch Tag",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Tag", description="The tag to fetch")


class SnowflakeCreateOrAlterTagConfig(BaseModel):
    """Create a tag, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_tag"] = Field(
        "create_or_alter_tag",
        json_schema_extra={
            "const": "create_or_alter_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Create or Alter Tag",
        },
        title="Create or Alter Tag",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the tag")
    allowed_values: Optional[str] = Field(None, title="Allowed Values", description="Comma-separated string values the tag may take")
    propagate: Optional[str] = Field(None, title="Propagate", description="Whether the tag propagates from source to target objects")
    on_conflict: Optional[str] = Field(None, title="On Conflict", description="Behavior when propagated tag values conflict")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the tag")


class SnowflakeDeleteTagConfig(BaseModel):
    """Drop a tag."""

    operation: Literal["delete_tag"] = Field(
        "delete_tag",
        json_schema_extra={
            "const": "delete_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Delete Tag",
        },
        title="Delete Tag",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Tag", description="The tag to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the tag is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUndropTagConfig(BaseModel):
    """Restore the most recently dropped tag of this name."""

    operation: Literal["undrop_tag"] = Field(
        "undrop_tag",
        json_schema_extra={
            "const": "undrop_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Undrop Tag",
        },
        title="Undrop Tag",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Tag", description="The tag to undrop")


class SnowflakeRenameTagConfig(BaseModel):
    """Rename a tag to a new identifier."""

    operation: Literal["rename_tag"] = Field(
        "rename_tag",
        json_schema_extra={
            "const": "rename_tag", "ui:hidden": True, "x-category": "Tags",
            "x-is-trigger": False, "x-display-name": "Rename Tag",
        },
        title="Rename Tag",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="Tag", description="The tag to rename")
    target_name: str = Field(..., title="New Name", description="Name of the renamed tag")
    target_database: Optional[str] = Field(None, title="Target Database", description="Defaults to the source database")
    target_schema: Optional[str] = Field(None, title="Target Schema", description="Defaults to the source schema")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the tag is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _sf_tag_body(c):
    return {
        "name": c.name,
        "allowed_values": [v.strip() for v in c.allowed_values.split(",") if v.strip()] if c.allowed_values else None,
        "propagate": c.propagate,
        "on_conflict": c.on_conflict,
        "comment": c.comment,
    }


async def _list_tags(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/tags"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_tags")


async def _create_tag(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/tags"
    params = {"createMode": c.create_mode} if c.create_mode else None
    return await node._request(account, token, "POST", base, params=params, json_body=_sf_tag_body(c), action_name="create_tag")


async def _fetch_tag(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tags/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_tag")


async def _create_or_alter_tag(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tags/{c.name}"
    return await node._request(account, token, "PUT", ep, json_body=_sf_tag_body(c), action_name="create_or_alter_tag")


async def _delete_tag(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tags/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_tag")


async def _undrop_tag(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tags/{c.name}:undrop"
    return await node._request(account, token, "POST", ep, action_name="undrop_tag")


async def _rename_tag(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tags/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_tag")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListTagsConfig,
    SnowflakeCreateTagConfig,
    SnowflakeFetchTagConfig,
    SnowflakeCreateOrAlterTagConfig,
    SnowflakeDeleteTagConfig,
    SnowflakeUndropTagConfig,
    SnowflakeRenameTagConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_tags": _list_tags,
    "create_tag": _create_tag,
    "fetch_tag": _fetch_tag,
    "create_or_alter_tag": _create_or_alter_tag,
    "delete_tag": _delete_tag,
    "undrop_tag": _undrop_tag,
    "rename_tag": _rename_tag,
})


# ---- task.py ----
class SnowflakeFetchTaskConfig(BaseModel):
    """Fetch a single task's definition."""

    operation: Literal["fetch_task"] = Field(
        "fetch_task",
        json_schema_extra={
            "const": "fetch_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Fetch Task",
        },
        title="Fetch Task",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to fetch")


class SnowflakeCreateOrAlterTaskConfig(BaseModel):
    """Create a task, or alter it to match if it already exists."""

    operation: Literal["create_or_alter_task"] = Field(
        "create_or_alter_task",
        json_schema_extra={
            "const": "create_or_alter_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Create or Alter Task",
        },
        title="Create or Alter Task",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the task")
    definition: str = Field(..., title="Definition", description="The SQL definition executed by the task")
    warehouse: Optional[str] = Field(None, title="Warehouse", description="Virtual warehouse for task runs (omit for serverless)")
    schedule: Optional[str] = Field(None, title="Schedule", description="JSON schedule object, e.g. {\"schedule_type\": \"MINUTES_TYPE\", \"minutes\": 10} or {\"schedule_type\": \"CRON_TYPE\", \"cron_expr\": \"* * * * ? *\", \"timezone\": \"UTC\"}")
    predecessors: Optional[str] = Field(None, title="Predecessors", description="Comma-separated predecessor task names")
    finalize: Optional[str] = Field(None, title="Finalize", description="Name of the root task this finalizer task is associated with")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the task")
    condition: Optional[str] = Field(None, title="Condition", description="Boolean SQL expression gating task execution")
    config: Optional[str] = Field(None, title="Config", description="JSON object of task config key/values")
    session_parameters: Optional[str] = Field(None, title="Session Parameters", description="JSON object of session parameters applied at runtime")
    task_auto_retry_attempts: Optional[str] = Field(None, title="Auto Retry Attempts", description="Number of automatic task graph retry attempts (0-30)")
    user_task_managed_initial_warehouse_size: Optional[str] = Field(None, title="Initial Warehouse Size", description="Compute size for the first run (serverless tasks only)")
    target_completion_interval: Optional[str] = Field(None, title="Target Completion Interval", description="JSON minutes schedule, e.g. {\"schedule_type\": \"MINUTES_TYPE\", \"minutes\": 5} (serverless tasks only)")
    serverless_task_min_statement_size: Optional[str] = Field(None, title="Min Statement Size", description="Minimum warehouse size for the serverless task (XSMALL-XXLARGE)")
    serverless_task_max_statement_size: Optional[str] = Field(None, title="Max Statement Size", description="Maximum warehouse size for the serverless task (XSMALL-XXLARGE)")
    user_task_timeout_ms: Optional[str] = Field(None, title="Timeout (ms)", description="Time limit on a single run before timeout")
    suspend_task_after_num_failures: Optional[str] = Field(None, title="Suspend After Failures", description="Suspend the task after this many consecutive failures")
    error_integration: Optional[str] = Field(None, title="Error Integration", description="Notification integration used for error notifications")
    success_integration: Optional[str] = Field(None, title="Success Integration", description="Notification integration used for success notifications")
    execute_as_user: Optional[str] = Field(None, title="Execute As User", description="User whose privileges are used to run the task")
    allow_overlapping_execution: Optional[str] = Field(
        None, title="Allow Overlapping Execution", description="Allow multiple concurrent DAG instances",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    overlap_policy: Optional[str] = Field(
        None, title="Overlap Policy", description="DAG overlap policy (root tasks only)",
        json_schema_extra={"enum": ["NO_OVERLAP", "ALLOW_CHILD_OVERLAP", "ALLOW_ALL_OVERLAP"], "x-enum-searchable": True},
    )


class SnowflakeDeleteTaskConfig(BaseModel):
    """Drop a task."""

    operation: Literal["delete_task"] = Field(
        "delete_task",
        json_schema_extra={
            "const": "delete_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Delete Task",
        },
        title="Delete Task",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the task is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchTaskDependentsConfig(BaseModel):
    """Fetch the dependent tasks of a task."""

    operation: Literal["fetch_task_dependents"] = Field(
        "fetch_task_dependents",
        json_schema_extra={
            "const": "fetch_task_dependents", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Fetch Task Dependents",
        },
        title="Fetch Task Dependents",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task whose dependents to fetch")
    recursive: Optional[str] = Field(
        None, title="Recursive", description="Include all recursive child tasks, not just direct children",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetCurrentGraphsDeprecatedConfig(BaseModel):
    """Get graph runs executing or scheduled for the task (deprecated path)."""

    operation: Literal["get_current_graphs_deprecated"] = Field(
        "get_current_graphs_deprecated",
        json_schema_extra={
            "const": "get_current_graphs_deprecated", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Get Current Graphs (Deprecated)",
        },
        title="Get Current Graphs (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task name")
    result_limit: Optional[str] = Field(None, title="Result Limit", description="Max results to return (1-10000, default 1000)")


class SnowflakeGetCurrentGraphsConfig(BaseModel):
    """Get graph runs executing or scheduled for the task."""

    operation: Literal["get_current_graphs"] = Field(
        "get_current_graphs",
        json_schema_extra={
            "const": "get_current_graphs", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Get Current Graphs",
        },
        title="Get Current Graphs",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task name")
    result_limit: Optional[str] = Field(None, title="Result Limit", description="Max results to return (1-10000, default 1000)")


class SnowflakeGetCompleteGraphsDeprecatedConfig(BaseModel):
    """Get completed graph runs for the task (deprecated path)."""

    operation: Literal["get_complete_graphs_deprecated"] = Field(
        "get_complete_graphs_deprecated",
        json_schema_extra={
            "const": "get_complete_graphs_deprecated", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Get Complete Graphs (Deprecated)",
        },
        title="Get Complete Graphs (Deprecated)",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task name")
    result_limit: Optional[str] = Field(None, title="Result Limit", description="Max results to return (1-10000, default 1000)")
    error_only: Optional[str] = Field(
        None, title="Error Only", description="Only return runs that have failed",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetCompleteGraphsConfig(BaseModel):
    """Get completed graph runs for the task."""

    operation: Literal["get_complete_graphs"] = Field(
        "get_complete_graphs",
        json_schema_extra={
            "const": "get_complete_graphs", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Get Complete Graphs",
        },
        title="Get Complete Graphs",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task name")
    result_limit: Optional[str] = Field(None, title="Result Limit", description="Max results to return (1-10000, default 1000)")
    error_only: Optional[str] = Field(
        None, title="Error Only", description="Only return runs that have failed",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetTagsTaskConfig(BaseModel):
    """Set a tag on an existing task."""

    operation: Literal["set_tags_task"] = Field(
        "set_tags_task",
        json_schema_extra={
            "const": "set_tags_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Set Task Tags",
        },
        title="Set Task Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the task is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsTaskConfig(BaseModel):
    """Unset a tag from an existing task."""

    operation: Literal["unset_tags_task"] = Field(
        "unset_tags_task",
        json_schema_extra={
            "const": "unset_tags_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Unset Task Tags",
        },
        title="Unset Task Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the task is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsTaskConfig(BaseModel):
    """Get the tag assignments for a task."""

    operation: Literal["get_tags_task"] = Field(
        "get_tags_task",
        json_schema_extra={
            "const": "get_tags_task", "ui:hidden": True, "x-category": "Tasks",
            "x-is-trigger": False, "x-display-name": "Get Task Tags",
        },
        title="Get Task Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Task", description="The task whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _fetch_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_task")


async def _create_or_alter_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}"
    body = {
        "name": c.name, "definition": c.definition, "warehouse": c.warehouse,
        "schedule": _sf_json(c.schedule) if c.schedule else None,
        "predecessors": [p.strip() for p in c.predecessors.split(",") if p.strip()] if c.predecessors else None,
        "finalize": c.finalize,
        "comment": c.comment, "condition": c.condition,
        "config": _sf_json(c.config) if c.config else None,
        "session_parameters": _sf_json(c.session_parameters) if c.session_parameters else None,
        "task_auto_retry_attempts": _sf_int(c.task_auto_retry_attempts),
        "user_task_managed_initial_warehouse_size": c.user_task_managed_initial_warehouse_size,
        "target_completion_interval": _sf_json(c.target_completion_interval) if c.target_completion_interval else None,
        "serverless_task_min_statement_size": c.serverless_task_min_statement_size,
        "serverless_task_max_statement_size": c.serverless_task_max_statement_size,
        "user_task_timeout_ms": _sf_int(c.user_task_timeout_ms),
        "suspend_task_after_num_failures": _sf_int(c.suspend_task_after_num_failures),
        "error_integration": c.error_integration,
        "success_integration": c.success_integration,
        "execute_as_user": c.execute_as_user,
        "allow_overlapping_execution": _sf_bool(c.allow_overlapping_execution),
        "overlap_policy": c.overlap_policy,
    }
    return await node._request(account, token, "PUT", ep, json_body=body, action_name="create_or_alter_task")


async def _delete_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_task")


async def _fetch_task_dependents(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/dependents"
    params = {"recursive": _sf_bool(c.recursive)}
    return await node._request(account, token, "GET", ep, params=params, action_name="fetch_task_dependents")


async def _get_current_graphs_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/current_graphs"
    params = {"resultLimit": _sf_int(c.result_limit)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_current_graphs_deprecated")


async def _get_current_graphs(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/current-graphs"
    params = {"resultLimit": _sf_int(c.result_limit)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_current_graphs")


async def _get_complete_graphs_deprecated(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/complete_graphs"
    params = {"resultLimit": _sf_int(c.result_limit), "errorOnly": _sf_bool(c.error_only)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_complete_graphs_deprecated")


async def _get_complete_graphs(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/complete-graphs"
    params = {"resultLimit": _sf_int(c.result_limit), "errorOnly": _sf_bool(c.error_only)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_complete_graphs")


async def _set_tags_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_tags_task")


async def _unset_tags_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_tags_task")


async def _get_tags_task(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_tags_task")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeFetchTaskConfig,
    SnowflakeCreateOrAlterTaskConfig,
    SnowflakeDeleteTaskConfig,
    SnowflakeFetchTaskDependentsConfig,
    SnowflakeGetCurrentGraphsDeprecatedConfig,
    SnowflakeGetCurrentGraphsConfig,
    SnowflakeGetCompleteGraphsDeprecatedConfig,
    SnowflakeGetCompleteGraphsConfig,
    SnowflakeSetTagsTaskConfig,
    SnowflakeUnsetTagsTaskConfig,
    SnowflakeGetTagsTaskConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "fetch_task": _fetch_task,
    "create_or_alter_task": _create_or_alter_task,
    "delete_task": _delete_task,
    "fetch_task_dependents": _fetch_task_dependents,
    "get_current_graphs_deprecated": _get_current_graphs_deprecated,
    "get_current_graphs": _get_current_graphs,
    "get_complete_graphs_deprecated": _get_complete_graphs_deprecated,
    "get_complete_graphs": _get_complete_graphs,
    "set_tags_task": _set_tags_task,
    "unset_tags_task": _unset_tags_task,
    "get_tags_task": _get_tags_task,
})


# ---- user.py ----
class SnowflakeFetchUserConfig(BaseModel):
    """Fetch information about a single user (DESCRIBE result)."""

    operation: Literal["fetch_user"] = Field(
        "fetch_user",
        json_schema_extra={
            "const": "fetch_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Fetch User",
        },
        title="Fetch User",
    )
    name: str = Field(..., title="User", description="The user to fetch")


class SnowflakeCreateOrAlterUserConfig(BaseModel):
    """Create a user, or alter it to match if it already exists (full property set required)."""

    operation: Literal["create_or_alter_user"] = Field(
        "create_or_alter_user",
        json_schema_extra={
            "const": "create_or_alter_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Create or Alter User",
        },
        title="Create or Alter User",
    )
    name: str = Field(..., title="Name", description="User name")
    password: Optional[str] = Field(None, title="Password", description="Password (only applied on create)")
    login_name: Optional[str] = Field(None, title="Login Name", description="Login name")
    display_name: Optional[str] = Field(None, title="Display Name", description="Display name")
    first_name: Optional[str] = Field(None, title="First Name", description="First name")
    middle_name: Optional[str] = Field(None, title="Middle Name", description="Middle name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Last name")
    email: Optional[str] = Field(None, title="Email", description="Email address")
    must_change_password: Optional[str] = Field(
        None, title="Must Change Password", description="Require the user to change their password",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    disabled: Optional[str] = Field(
        None, title="Disabled", description="Whether the user is disabled from the system",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    days_to_expiry: Optional[str] = Field(None, title="Days To Expiry", description="How many days until this user expires")
    mins_to_unlock: Optional[str] = Field(None, title="Minutes To Unlock", description="Minutes until the account unlocks after failed logins")
    default_warehouse: Optional[str] = Field(None, title="Default Warehouse", description="Default warehouse for new sessions")
    default_namespace: Optional[str] = Field(None, title="Default Namespace", description="Default namespace for new sessions")
    default_role: Optional[str] = Field(None, title="Default Role", description="Default role for new sessions")
    default_secondary_roles: Optional[str] = Field(
        None, title="Default Secondary Roles", description="Default secondary roles (ALL or NONE)",
        json_schema_extra={"enum": ["ALL", "NONE"], "x-enum-searchable": True},
    )
    mins_to_bypass_mfa: Optional[str] = Field(None, title="Minutes To Bypass MFA", description="Minutes until MFA is required again")
    rsa_public_key: Optional[str] = Field(None, title="RSA Public Key", description="RSA public key of the user")
    rsa_public_key_2: Optional[str] = Field(None, title="RSA Public Key 2", description="Second RSA public key of the user")
    comment: Optional[str] = Field(None, title="Comment", description="Comment about the user")
    type: Optional[str] = Field(None, title="Type", description="Type of user (PERSON | SERVICE | LEGACY_SERVICE)")
    enable_unredacted_query_syntax_error: Optional[str] = Field(
        None, title="Unredacted Query Syntax Errors", description="Show unredacted query syntax errors in query history",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    network_policy: Optional[str] = Field(None, title="Network Policy", description="Existing network policy active for the user")


class SnowflakeListGrantsUserConfig(BaseModel):
    """List all grants (roles) granted to the user."""

    operation: Literal["list_grants_user"] = Field(
        "list_grants_user",
        json_schema_extra={
            "const": "list_grants_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "List Grants To User",
        },
        title="List Grants To User",
    )
    name: str = Field(..., title="User", description="The user whose grants to list")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")


class SnowflakeGrantUserConfig(BaseModel):
    """Grant a role to the user."""

    operation: Literal["grant_user"] = Field(
        "grant_user",
        json_schema_extra={
            "const": "grant_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Grant Role To User",
        },
        title="Grant Role To User",
    )
    name: str = Field(..., title="User", description="The user to grant a role to")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be granted (only ROLE is supported)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to grant")
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable (e.g. the role name)")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")


class SnowflakeRevokeGrantsUserConfig(BaseModel):
    """Revoke grants (roles) from the user."""

    operation: Literal["revoke_grants_user"] = Field(
        "revoke_grants_user",
        json_schema_extra={
            "const": "revoke_grants_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Revoke Grants From User",
        },
        title="Revoke Grants From User",
    )
    name: str = Field(..., title="User", description="The user to revoke grants from")
    securable_type: str = Field(..., title="Securable Type", description="Type of the securable to be revoked (only ROLE is supported)")
    privileges: Optional[str] = Field(None, title="Privileges", description="Comma-separated list of privileges to revoke")
    securable_database: Optional[str] = Field(None, title="Securable Database", description="Database name of the securable if applicable")
    securable_schema: Optional[str] = Field(None, title="Securable Schema", description="Schema name of the securable if applicable")
    securable_name: Optional[str] = Field(None, title="Securable Name", description="Name of the securable (e.g. the role name)")
    scope_database: Optional[str] = Field(None, title="Scope Database", description="Database name of the containing scope if applicable")
    scope_schema: Optional[str] = Field(None, title="Scope Schema", description="Schema name of the containing scope if applicable")


class SnowflakeSetTagsUserConfig(BaseModel):
    """Set tags on a user."""

    operation: Literal["set_tags_user"] = Field(
        "set_tags_user",
        json_schema_extra={
            "const": "set_tags_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Set Tags On User",
        },
        title="Set Tags On User",
    )
    name: str = Field(..., title="User", description="The user to tag")
    tags: str = Field(
        ..., title="Tags",
        description='Comma-separated tag assignments as "name=value" pairs, e.g. "cost_center=eng, env=prod"',
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the user is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetTagsUserConfig(BaseModel):
    """Unset tags from a user."""

    operation: Literal["unset_tags_user"] = Field(
        "unset_tags_user",
        json_schema_extra={
            "const": "unset_tags_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Unset Tags From User",
        },
        title="Unset Tags From User",
    )
    name: str = Field(..., title="User", description="The user to untag")
    tags: str = Field(..., title="Tag Names", description="Comma-separated tag names to unset")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the user is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetTagsUserConfig(BaseModel):
    """Get the tag assignments for a user (requires an active warehouse)."""

    operation: Literal["get_tags_user"] = Field(
        "get_tags_user",
        json_schema_extra={
            "const": "get_tags_user", "ui:hidden": True, "x-category": "Users",
            "x-is-trigger": False, "x-display-name": "Get Tags On User",
        },
        title="Get Tags On User",
    )
    name: str = Field(..., title="User", description="The user whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


def _user_grant_body(c):
    securable = {k: v for k, v in {
        "database": c.securable_database, "schema": c.securable_schema,
        "name": c.securable_name}.items() if v}
    containing_scope = {k: v for k, v in {
        "database": c.scope_database, "schema": c.scope_schema}.items() if v}
    body = {
        "securable_type": c.securable_type,
        "privileges": [p.strip() for p in c.privileges.split(",") if p.strip()] if c.privileges else None,
    }
    if securable:
        body["securable"] = securable
    if containing_scope:
        body["containing_scope"] = containing_scope
    return body


async def _fetch_user(node, c, account, token):
    return await node._request(account, token, "GET", f"/users/{c.name}", action_name="fetch_user")


async def _create_or_alter_user(node, c, account, token):
    body = {
        "name": c.name, "password": c.password, "login_name": c.login_name,
        "display_name": c.display_name, "first_name": c.first_name, "middle_name": c.middle_name,
        "last_name": c.last_name, "email": c.email,
        "must_change_password": _sf_bool(c.must_change_password), "disabled": _sf_bool(c.disabled),
        "days_to_expiry": _sf_int(c.days_to_expiry), "mins_to_unlock": _sf_int(c.mins_to_unlock),
        "default_warehouse": c.default_warehouse, "default_namespace": c.default_namespace,
        "default_role": c.default_role, "default_secondary_roles": c.default_secondary_roles,
        "mins_to_bypass_mfa": _sf_int(c.mins_to_bypass_mfa), "rsa_public_key": c.rsa_public_key,
        "rsa_public_key_2": c.rsa_public_key_2, "comment": c.comment, "type": c.type,
        "enable_unredacted_query_syntax_error": _sf_bool(c.enable_unredacted_query_syntax_error),
        "network_policy": c.network_policy,
    }
    return await node._request(account, token, "PUT", f"/users/{c.name}", json_body=body, action_name="create_or_alter_user")


async def _list_grants_user(node, c, account, token):
    params = {"showLimit": c.show_limit}
    return await node._request(account, token, "GET", f"/users/{c.name}/grants", params=params, action_name="list_grants_user")


async def _grant_user(node, c, account, token):
    return await node._request(account, token, "POST", f"/users/{c.name}/grants",
                               json_body=_user_grant_body(c), action_name="grant_user")


async def _revoke_grants_user(node, c, account, token):
    return await node._request(account, token, "POST", f"/users/{c.name}/grants:revoke",
                               json_body=_user_grant_body(c), action_name="revoke_grants_user")


async def _set_tags_user(node, c, account, token):
    body = []
    for pair in c.tags.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tag_name, _, tag_value = pair.partition("=")
        body.append({"name": tag_name.strip(), "value": tag_value.strip()})
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/users/{c.name}:set-tags",
                               params=params, json_body=body, action_name="set_tags_user")


async def _unset_tags_user(node, c, account, token):
    body = [{"name": t.strip()} for t in c.tags.split(",") if t.strip()]
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", f"/users/{c.name}:unset-tags",
                               params=params, json_body=body, action_name="unset_tags_user")


async def _get_tags_user(node, c, account, token):
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", f"/users/{c.name}:get-tags", params=params, action_name="get_tags_user")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeFetchUserConfig,
    SnowflakeCreateOrAlterUserConfig,
    SnowflakeListGrantsUserConfig,
    SnowflakeGrantUserConfig,
    SnowflakeRevokeGrantsUserConfig,
    SnowflakeSetTagsUserConfig,
    SnowflakeUnsetTagsUserConfig,
    SnowflakeGetTagsUserConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "fetch_user": _fetch_user,
    "create_or_alter_user": _create_or_alter_user,
    "list_grants_user": _list_grants_user,
    "grant_user": _grant_user,
    "revoke_grants_user": _revoke_grants_user,
    "set_tags_user": _set_tags_user,
    "unset_tags_user": _unset_tags_user,
    "get_tags_user": _get_tags_user,
})


# ---- user_defined_function.py ----
class SnowflakeListUserDefinedFunctionsConfig(BaseModel):
    """List user-defined functions in a schema."""

    operation: Literal["list_user_defined_functions"] = Field(
        "list_user_defined_functions",
        json_schema_extra={
            "const": "list_user_defined_functions", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "List User-Defined Functions",
        },
        title="List User-Defined Functions",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")


class SnowflakeCreateUserDefinedFunctionConfig(BaseModel):
    """Create a user-defined function in a schema."""

    operation: Literal["create_user_defined_function"] = Field(
        "create_user_defined_function",
        json_schema_extra={
            "const": "create_user_defined_function", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Create User-Defined Function",
        },
        title="Create User-Defined Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the UDF to create")
    arguments: Optional[str] = Field(
        None, title="Arguments",
        description="JSON array of UDF arguments, e.g. [{\"name\":\"x\",\"datatype\":\"TEXT\"}]",
    )
    return_type: Optional[str] = Field(
        None, title="Return Type",
        description="JSON object for the return type, e.g. {\"type\":\"DATATYPE\",\"datatype\":\"TEXT\"}",
    )
    language_config: Optional[str] = Field(
        None, title="Language Config",
        description="JSON object describing the language, e.g. {\"language\":\"SQL\"}",
    )
    body: Optional[str] = Field(None, title="Body", description="UDF definition (function body)")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the UDF")
    is_secure: Optional[str] = Field(
        None, title="Is Secure", description="Whether the UDF is secure",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    is_temporary: Optional[str] = Field(
        None, title="Is Temporary", description="Whether the UDF is temporary",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    is_aggregate: Optional[str] = Field(
        None, title="Is Aggregate", description="Whether the UDF is an aggregate function (Python only)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    is_memoizable: Optional[str] = Field(
        None, title="Is Memoizable", description="Whether the function is memoizable (Python only)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the UDF already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Retain existing grants when replacing the UDF",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchUserDefinedFunctionConfig(BaseModel):
    """Fetch a single UDF's definition."""

    operation: Literal["fetch_user_defined_function"] = Field(
        "fetch_user_defined_function",
        json_schema_extra={
            "const": "fetch_user_defined_function", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Fetch User-Defined Function",
        },
        title="Fetch User-Defined Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")


class SnowflakeDeleteUserDefinedFunctionConfig(BaseModel):
    """Drop a UDF."""

    operation: Literal["delete_user_defined_function"] = Field(
        "delete_user_defined_function",
        json_schema_extra={
            "const": "delete_user_defined_function", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Delete User-Defined Function",
        },
        title="Delete User-Defined Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the UDF is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeExecuteUserDefinedFunctionConfig(BaseModel):
    """Execute a UDF with the given arguments."""

    operation: Literal["execute_user_defined_function"] = Field(
        "execute_user_defined_function",
        json_schema_extra={
            "const": "execute_user_defined_function", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Execute User-Defined Function",
        },
        title="Execute User-Defined Function",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="The UDF to execute")
    arguments: Optional[str] = Field(
        None, title="Arguments",
        description="JSON array of argument objects, e.g. [{\"name\":\"x\",\"datatype\":\"TEXT\",\"value\":\"hi\"}]",
    )


class SnowflakeRenameUserDefinedFunctionConfig(BaseModel):
    """Rename a UDF to a new identifier."""

    operation: Literal["rename_user_defined_function"] = Field(
        "rename_user_defined_function",
        json_schema_extra={
            "const": "rename_user_defined_function", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Rename User-Defined Function",
        },
        title="Rename User-Defined Function",
    )
    database: str = Field(
        ..., title="Database", description="Source database",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="Source schema")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")
    target_database: str = Field(..., title="Target Database", description="Database of the target UDF")
    target_schema: str = Field(..., title="Target Schema", description="Schema of the target UDF")
    target_name: str = Field(..., title="New Name", description="Name of the renamed UDF")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the UDF is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetUserDefinedFunctionTagsConfig(BaseModel):
    """Set tags on a UDF."""

    operation: Literal["set_user_defined_function_tags"] = Field(
        "set_user_defined_function_tags",
        json_schema_extra={
            "const": "set_user_defined_function_tags", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Set User-Defined Function Tags",
        },
        title="Set User-Defined Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")
    tags: Optional[str] = Field(
        None, title="Tags",
        description="JSON array of tag assignments, e.g. [{\"name\":\"cost_center\",\"value\":\"eng\"}]",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the UDF is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetUserDefinedFunctionTagsConfig(BaseModel):
    """Unset tags from a UDF."""

    operation: Literal["unset_user_defined_function_tags"] = Field(
        "unset_user_defined_function_tags",
        json_schema_extra={
            "const": "unset_user_defined_function_tags", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Unset User-Defined Function Tags",
        },
        title="Unset User-Defined Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")
    tags: Optional[str] = Field(
        None, title="Tags",
        description="JSON array of tag references, e.g. [{\"name\":\"cost_center\"}]",
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the UDF is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetUserDefinedFunctionTagsConfig(BaseModel):
    """Get the tag assignments for a UDF."""

    operation: Literal["get_user_defined_function_tags"] = Field(
        "get_user_defined_function_tags",
        json_schema_extra={
            "const": "get_user_defined_function_tags", "ui:hidden": True, "x-category": "User-Defined Functions",
            "x-is-trigger": False, "x-display-name": "Get User-Defined Function Tags",
        },
        title="Get User-Defined Function Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="UDF", description="UDF name with arguments, e.g. my_udf(TEXT)")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags propagated via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_user_defined_functions(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions"
    params = {"like": c.like}
    return await node._request(account, token, "GET", base, params=params, action_name="list_user_defined_functions")


async def _create_user_defined_function(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions"
    body = {"name": c.name, "arguments": c.arguments, "return_type": c.return_type,
            "language_config": c.language_config, "body": c.body, "comment": c.comment,
            "is_secure": _sf_bool(c.is_secure), "is_temporary": _sf_bool(c.is_temporary),
            "is_aggregate": _sf_bool(c.is_aggregate), "is_memoizable": _sf_bool(c.is_memoizable)}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_user_defined_function")


async def _fetch_user_defined_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_user_defined_function")


async def _delete_user_defined_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_user_defined_function")


async def _execute_user_defined_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}:execute"
    body = {"arguments": c.arguments}
    return await node._request(account, token, "POST", ep, json_body=body, action_name="execute_user_defined_function")


async def _rename_user_defined_function(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists), "targetDatabase": c.target_database,
              "targetSchema": c.target_schema, "targetName": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, action_name="rename_user_defined_function")


async def _set_user_defined_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"tags": c.tags}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_user_defined_function_tags")


async def _unset_user_defined_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"tags": c.tags}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_user_defined_function_tags")


async def _get_user_defined_function_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/user-defined-functions/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_user_defined_function_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListUserDefinedFunctionsConfig,
    SnowflakeCreateUserDefinedFunctionConfig,
    SnowflakeFetchUserDefinedFunctionConfig,
    SnowflakeDeleteUserDefinedFunctionConfig,
    SnowflakeExecuteUserDefinedFunctionConfig,
    SnowflakeRenameUserDefinedFunctionConfig,
    SnowflakeSetUserDefinedFunctionTagsConfig,
    SnowflakeUnsetUserDefinedFunctionTagsConfig,
    SnowflakeGetUserDefinedFunctionTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_user_defined_functions": _list_user_defined_functions,
    "create_user_defined_function": _create_user_defined_function,
    "fetch_user_defined_function": _fetch_user_defined_function,
    "delete_user_defined_function": _delete_user_defined_function,
    "execute_user_defined_function": _execute_user_defined_function,
    "rename_user_defined_function": _rename_user_defined_function,
    "set_user_defined_function_tags": _set_user_defined_function_tags,
    "unset_user_defined_function_tags": _unset_user_defined_function_tags,
    "get_user_defined_function_tags": _get_user_defined_function_tags,
})


# ---- view.py ----
class SnowflakeListViewsConfig(BaseModel):
    """List views in a schema."""

    operation: Literal["list_views"] = Field(
        "list_views",
        json_schema_extra={
            "const": "list_views", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "List Views",
        },
        title="List Views",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    like: Optional[str] = Field(None, title="Like", description="Case-insensitive name pattern filter")
    starts_with: Optional[str] = Field(None, title="Starts With", description="Case-sensitive name prefix filter")
    show_limit: Optional[str] = Field(None, title="Limit", description="Maximum number of rows to return")
    from_name: Optional[str] = Field(None, title="From Name", description="Return rows after this name (pagination)")
    deep: Optional[str] = Field(
        None, title="Deep", description="Include dependency information of the view",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateViewConfig(BaseModel):
    """Create a view in a schema."""

    operation: Literal["create_view"] = Field(
        "create_view",
        json_schema_extra={
            "const": "create_view", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Create View",
        },
        title="Create View",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="Name", description="Name of the view to create")
    query: str = Field(..., title="Query", description="Query used to create the view")
    columns: str = Field(
        ..., title="Columns",
        description='JSON array of the view columns, e.g. [{"name": "id"}, {"name": "email", "comment": "..."}]',
    )
    secure: Optional[str] = Field(
        None, title="Secure", description="Whether this view is secure",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    kind: Optional[str] = Field(
        None, title="Kind", description="Kind of the view, permanent (default) or temporary",
        json_schema_extra={"enum": ["PERMANENT", "TEMPORARY"], "x-enum-searchable": True},
    )
    recursive: Optional[str] = Field(
        None, title="Recursive", description="Whether the view can refer to itself recursively",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the view")
    create_mode: Optional[str] = Field(
        "errorIfExists", title="Create Mode",
        description="Behavior when the view already exists",
        json_schema_extra={"enum": ["errorIfExists", "orReplace", "ifNotExists"], "x-enum-searchable": True},
    )
    copy_grants: Optional[str] = Field(
        None, title="Copy Grants", description="Copy grants from the existing view when replacing",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeFetchViewConfig(BaseModel):
    """Fetch a single view's definition."""

    operation: Literal["fetch_view"] = Field(
        "fetch_view",
        json_schema_extra={
            "const": "fetch_view", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Fetch View",
        },
        title="Fetch View",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="View", description="The view to fetch")


class SnowflakeDeleteViewConfig(BaseModel):
    """Drop a view."""

    operation: Literal["delete_view"] = Field(
        "delete_view",
        json_schema_extra={
            "const": "delete_view", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Delete View",
        },
        title="Delete View",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="View", description="The view to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the view is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetViewTagsConfig(BaseModel):
    """Set tags on a view."""

    operation: Literal["set_view_tags"] = Field(
        "set_view_tags",
        json_schema_extra={
            "const": "set_view_tags", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Set View Tags",
        },
        title="Set View Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="View", description="The view to tag")
    tags: str = Field(
        ..., title="Tags",
        description='JSON array of tag assignments, e.g. [{"name": "cost_center", "value": "sales"}]',
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the view is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetViewTagsConfig(BaseModel):
    """Unset tags from a view."""

    operation: Literal["unset_view_tags"] = Field(
        "unset_view_tags",
        json_schema_extra={
            "const": "unset_view_tags", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Unset View Tags",
        },
        title="Unset View Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="View", description="The view to untag")
    tags: str = Field(
        ..., title="Tags",
        description='JSON array of tag references to remove, e.g. [{"name": "cost_center"}]',
    )
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the view is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetViewTagsConfig(BaseModel):
    """Get the tag assignments for a view (requires an active warehouse)."""

    operation: Literal["get_view_tags"] = Field(
        "get_view_tags",
        json_schema_extra={
            "const": "get_view_tags", "ui:hidden": True, "x-category": "Views",
            "x-is-trigger": False, "x-display-name": "Get View Tags",
        },
        title="Get View Tags",
    )
    database: str = Field(
        ..., title="Database", description="The database name",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "database", "placeholder": "Select a database...",
            "searchable": True, "allow_custom": True,
            "custom_placeholder": "Or type a database name"}},
    )
    schema_name: str = Field(..., title="Schema", description="The schema name")
    name: str = Field(..., title="View", description="The view whose tags to read")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _list_views(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/views"
    params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit,
              "fromName": c.from_name, "deep": _sf_bool(c.deep)}
    return await node._request(account, token, "GET", base, params=params, action_name="list_views")


async def _create_view(node, c, account, token):
    base = f"/databases/{c.database}/schemas/{c.schema_name}/views"
    body = {"name": c.name, "query": c.query, "columns": _sf_json(c.columns),
            "secure": _sf_bool(c.secure), "kind": c.kind, "recursive": _sf_bool(c.recursive),
            "comment": c.comment}
    params = {"createMode": c.create_mode, "copyGrants": _sf_bool(c.copy_grants)}
    return await node._request(account, token, "POST", base, params=params, json_body=body, action_name="create_view")


async def _fetch_view(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/views/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_view")


async def _delete_view(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/views/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_view")


async def _set_view_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/views/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = _sf_json(c.tags)
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_view_tags")


async def _unset_view_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/views/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = _sf_json(c.tags)
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_view_tags")


async def _get_view_tags(node, c, account, token):
    ep = f"/databases/{c.database}/schemas/{c.schema_name}/views/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_view_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeListViewsConfig,
    SnowflakeCreateViewConfig,
    SnowflakeFetchViewConfig,
    SnowflakeDeleteViewConfig,
    SnowflakeSetViewTagsConfig,
    SnowflakeUnsetViewTagsConfig,
    SnowflakeGetViewTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "list_views": _list_views,
    "create_view": _create_view,
    "fetch_view": _fetch_view,
    "delete_view": _delete_view,
    "set_view_tags": _set_view_tags,
    "unset_view_tags": _unset_view_tags,
    "get_view_tags": _get_view_tags,
})


# ---- warehouse.py ----
class SnowflakeFetchWarehouseConfig(BaseModel):
    """Describe a single warehouse."""

    operation: Literal["fetch_warehouse"] = Field(
        "fetch_warehouse",
        json_schema_extra={
            "const": "fetch_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Fetch Warehouse",
        },
        title="Fetch Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to describe")


class SnowflakeDeleteWarehouseConfig(BaseModel):
    """Drop a warehouse."""

    operation: Literal["delete_warehouse"] = Field(
        "delete_warehouse",
        json_schema_extra={
            "const": "delete_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Delete Warehouse",
        },
        title="Delete Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to drop")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeCreateOrAlterWarehouseConfig(BaseModel):
    """Create a warehouse, or alter it to match if it already exists (full property set required)."""

    operation: Literal["create_or_alter_warehouse"] = Field(
        "create_or_alter_warehouse",
        json_schema_extra={
            "const": "create_or_alter_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Create or Alter Warehouse",
        },
        title="Create or Alter Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="Name of the warehouse")
    warehouse_type: Optional[str] = Field(None, title="Type", description="STANDARD or SNOWPARK-OPTIMIZED")
    warehouse_size: Optional[str] = Field(None, title="Size", description="XSMALL, SMALL, MEDIUM, LARGE, XLARGE, XXLARGE, ...")
    wait_for_completion: Optional[str] = Field(
        None, title="Wait For Completion", description="Block until a resize finishes provisioning",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    max_cluster_count: Optional[str] = Field(None, title="Max Cluster Count", description="Max clusters for a multi-cluster warehouse")
    min_cluster_count: Optional[str] = Field(None, title="Min Cluster Count", description="Min clusters for a multi-cluster warehouse")
    scaling_policy: Optional[str] = Field(None, title="Scaling Policy", description="STANDARD or ECONOMY")
    auto_suspend: Optional[str] = Field(None, title="Auto Suspend", description="Time in seconds before auto-suspend")
    auto_resume: Optional[str] = Field(
        None, title="Auto Resume", description="Automatically resume when a statement is submitted",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    initially_suspended: Optional[str] = Field(
        None, title="Initially Suspended", description="Create the warehouse in the Suspended state",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    resource_monitor: Optional[str] = Field(None, title="Resource Monitor", description="Resource monitor assigned to the warehouse")
    comment: Optional[str] = Field(None, title="Comment", description="Comment for the warehouse")
    enable_query_acceleration: Optional[str] = Field(
        None, title="Enable Query Acceleration", description="Enable the query acceleration service",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    query_acceleration_max_scale_factor: Optional[str] = Field(None, title="Query Acceleration Max Scale Factor", description="Max scale factor for query acceleration")
    max_concurrency_level: Optional[str] = Field(None, title="Max Concurrency Level", description="Concurrency level for statements on a cluster")
    statement_queued_timeout_in_seconds: Optional[str] = Field(None, title="Statement Queued Timeout (s)", description="Seconds a statement may be queued before cancel")
    statement_timeout_in_seconds: Optional[str] = Field(None, title="Statement Timeout (s)", description="Seconds after which a running statement is canceled")
    warehouse_credit_limit: Optional[str] = Field(None, title="Warehouse Credit Limit", description="Credit limit for the warehouse")
    target_statement_size: Optional[str] = Field(None, title="Target Statement Size", description="X-Small, Small, Medium, Large, ...")


class SnowflakeRenameWarehouseConfig(BaseModel):
    """Rename a warehouse to a new identifier."""

    operation: Literal["rename_warehouse"] = Field(
        "rename_warehouse",
        json_schema_extra={
            "const": "rename_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Rename Warehouse",
        },
        title="Rename Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to rename")
    target_name: str = Field(..., title="New Name", description="New identifier for the warehouse")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUseWarehouseConfig(BaseModel):
    """[Deprecated] Set the active warehouse for the session."""

    operation: Literal["use_warehouse"] = Field(
        "use_warehouse",
        json_schema_extra={
            "const": "use_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Use Warehouse",
        },
        title="Use Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to make active for the session")


class SnowflakeEnableWarehouseConfig(BaseModel):
    """Enable an adaptive warehouse."""

    operation: Literal["enable_warehouse"] = Field(
        "enable_warehouse",
        json_schema_extra={
            "const": "enable_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Enable Warehouse",
        },
        title="Enable Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The adaptive warehouse to enable")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeDisableWarehouseConfig(BaseModel):
    """Disable an adaptive warehouse."""

    operation: Literal["disable_warehouse"] = Field(
        "disable_warehouse",
        json_schema_extra={
            "const": "disable_warehouse", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Disable Warehouse",
        },
        title="Disable Warehouse",
    )
    name: str = Field(..., title="Warehouse", description="The adaptive warehouse to disable")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeSetWarehouseTagsConfig(BaseModel):
    """Set a tag on a warehouse."""

    operation: Literal["set_warehouse_tags"] = Field(
        "set_warehouse_tags",
        json_schema_extra={
            "const": "set_warehouse_tags", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Set Warehouse Tags",
        },
        title="Set Warehouse Tags",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to tag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to set")
    tag_value: str = Field(..., title="Tag Value", description="Value to assign to the tag")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeUnsetWarehouseTagsConfig(BaseModel):
    """Unset a tag from a warehouse."""

    operation: Literal["unset_warehouse_tags"] = Field(
        "unset_warehouse_tags",
        json_schema_extra={
            "const": "unset_warehouse_tags", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Unset Warehouse Tags",
        },
        title="Unset Warehouse Tags",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse to untag")
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to remove")
    if_exists: Optional[str] = Field(
        None, title="If Exists", description="Do not error if the warehouse is absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class SnowflakeGetWarehouseTagsConfig(BaseModel):
    """Get the tag assignments for a warehouse (requires an active warehouse)."""

    operation: Literal["get_warehouse_tags"] = Field(
        "get_warehouse_tags",
        json_schema_extra={
            "const": "get_warehouse_tags", "ui:hidden": True, "x-category": "Warehouses",
            "x-is-trigger": False, "x-display-name": "Get Warehouse Tags",
        },
        title="Get Warehouse Tags",
    )
    name: str = Field(..., title="Warehouse", description="The warehouse whose tags to fetch")
    with_lineage: Optional[str] = Field(
        None, title="With Lineage", description="Include tags inherited via lineage",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _fetch_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}"
    return await node._request(account, token, "GET", ep, action_name="fetch_warehouse")


async def _delete_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "DELETE", ep, params=params, action_name="delete_warehouse")


async def _create_or_alter_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}"
    body = {
        "name": c.name,
        "warehouse_type": c.warehouse_type,
        "warehouse_size": c.warehouse_size,
        "wait_for_completion": _sf_bool(c.wait_for_completion),
        "max_cluster_count": _sf_int(c.max_cluster_count),
        "min_cluster_count": _sf_int(c.min_cluster_count),
        "scaling_policy": c.scaling_policy,
        "auto_suspend": _sf_int(c.auto_suspend),
        "auto_resume": _sf_bool(c.auto_resume),
        "initially_suspended": _sf_bool(c.initially_suspended),
        "resource_monitor": c.resource_monitor,
        "comment": c.comment,
        "enable_query_acceleration": _sf_bool(c.enable_query_acceleration),
        "query_acceleration_max_scale_factor": _sf_int(c.query_acceleration_max_scale_factor),
        "max_concurrency_level": _sf_int(c.max_concurrency_level),
        "statement_queued_timeout_in_seconds": _sf_int(c.statement_queued_timeout_in_seconds),
        "statement_timeout_in_seconds": _sf_int(c.statement_timeout_in_seconds),
        "warehouse_credit_limit": _sf_int(c.warehouse_credit_limit),
        "target_statement_size": c.target_statement_size,
    }
    return await node._request(account, token, "PUT", ep, json_body=body, action_name="create_or_alter_warehouse")


async def _rename_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}:rename"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = {"name": c.target_name}
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="rename_warehouse")


async def _use_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}:use"
    return await node._request(account, token, "POST", ep, action_name="use_warehouse")


async def _enable_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}:enable"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="enable_warehouse")


async def _disable_warehouse(node, c, account, token):
    ep = f"/warehouses/{c.name}:disable"
    params = {"ifExists": _sf_bool(c.if_exists)}
    return await node._request(account, token, "POST", ep, params=params, action_name="disable_warehouse")


async def _set_warehouse_tags(node, c, account, token):
    ep = f"/warehouses/{c.name}:set-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name, "value": c.tag_value}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="set_warehouse_tags")


async def _unset_warehouse_tags(node, c, account, token):
    ep = f"/warehouses/{c.name}:unset-tags"
    params = {"ifExists": _sf_bool(c.if_exists)}
    body = [{"name": c.tag_name}]
    return await node._request(account, token, "POST", ep, params=params, json_body=body, action_name="unset_warehouse_tags")


async def _get_warehouse_tags(node, c, account, token):
    ep = f"/warehouses/{c.name}:get-tags"
    params = {"withLineage": _sf_bool(c.with_lineage)}
    return await node._request(account, token, "GET", ep, params=params, action_name="get_warehouse_tags")


SNOWFLAKE_OPERATION_CONFIGS += [
    SnowflakeFetchWarehouseConfig,
    SnowflakeDeleteWarehouseConfig,
    SnowflakeCreateOrAlterWarehouseConfig,
    SnowflakeRenameWarehouseConfig,
    SnowflakeUseWarehouseConfig,
    SnowflakeEnableWarehouseConfig,
    SnowflakeDisableWarehouseConfig,
    SnowflakeSetWarehouseTagsConfig,
    SnowflakeUnsetWarehouseTagsConfig,
    SnowflakeGetWarehouseTagsConfig,
]
SNOWFLAKE_OPERATION_HANDLERS.update({
    "fetch_warehouse": _fetch_warehouse,
    "delete_warehouse": _delete_warehouse,
    "create_or_alter_warehouse": _create_or_alter_warehouse,
    "rename_warehouse": _rename_warehouse,
    "use_warehouse": _use_warehouse,
    "enable_warehouse": _enable_warehouse,
    "disable_warehouse": _disable_warehouse,
    "set_warehouse_tags": _set_warehouse_tags,
    "unset_warehouse_tags": _unset_warehouse_tags,
    "get_warehouse_tags": _get_warehouse_tags,
})


SnowflakeConfig = Annotated[
    Union[
        SnowflakeRunStatementConfig,
        SnowflakeGetStatementConfig,
        SnowflakeCancelStatementConfig,
        SnowflakeListDatabasesConfig,
        SnowflakeCreateDatabaseConfig,
        SnowflakeFetchDatabaseConfig,
        SnowflakeDeleteDatabaseConfig,
        SnowflakeListSchemasConfig,
        SnowflakeListTablesConfig,
        SnowflakeFetchTableConfig,
        SnowflakeListWarehousesConfig,
        SnowflakeCreateWarehouseConfig,
        SnowflakeResumeWarehouseConfig,
        SnowflakeSuspendWarehouseConfig,
        SnowflakeAbortWarehouseConfig,
        SnowflakeListTasksConfig,
        SnowflakeCreateTaskConfig,
        SnowflakeExecuteTaskConfig,
        SnowflakeResumeTaskConfig,
        SnowflakeSuspendTaskConfig,
        SnowflakeTaskHistoryConfig,
        SnowflakeListUsersConfig,
        SnowflakeCreateUserConfig,
        SnowflakeDeleteUserConfig,
        SnowflakeListRolesConfig,
        SnowflakeListStagesConfig,
        SnowflakeOnQueryResultsConfig,
        *SNOWFLAKE_OPERATION_CONFIGS,
    ],
    Discriminator("operation"),
]


class SnowflakeNodeConfig(NodeConfig[SnowflakeConfig, SnowflakeCredential]):
    """Full configuration for the Snowflake node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _snowflake_request(
    account_identifier: str,
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    token_type: str = "PROGRAMMATIC_ACCESS_TOKEN",
) -> Dict[str, Any]:
    """Make an authenticated Snowflake REST API v2 request.

    Snowflake returns 200 for finished statements and 202 for in-progress async
    statements; both are surfaced as success so callers can inspect the body.
    The `X-Snowflake-Authorization-Token-Type` header tells Snowflake how to
    interpret the bearer token (a PAT vs an OAuth access token).
    """
    url = f"{_account_host(account_identifier)}/api/v2{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Snowflake-Authorization-Token-Type": token_type,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "NoClick-Workflow/1.0",
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
                        or err.get("code")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[SnowflakeNode] API error ({action_name}): {message}")
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
            logger.error(f"[SnowflakeNode] Request failed ({action_name}): {msg}")
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


class SnowflakeNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Snowflake data-cloud automation node.

    ScheduledPollTriggerMixin (mixed in before WorkflowNode) owns the
    on_query_results trigger's generic plumbing: webhook + cron-schedule
    provisioning (load_field_value), teardown (cleanup_external_webhook), the
    resolve_trigger_payload wake-up short-circuit, and the trigger_produced_no_event
    skip. The node keeps its own cursor-based dedup in _on_query_results.
    """

    edit_examples = [
        "Run a SELECT query against a Snowflake table",
        "Insert rows into a Snowflake table with a SQL statement",
        "List all databases in the Snowflake account",
        "Resume a warehouse before running heavy queries",
        "Execute a scheduled Snowflake task on demand",
    ]

    # Bearer-token interpretation header value — always a Programmatic Access
    # Token (PAT is the only supported Snowflake credential).
    _token_type: str = "PROGRAMMATIC_ACCESS_TOKEN"

    @classmethod
    def get_config_model(cls):
        return SnowflakeNodeConfig

    # Inline "Create new <resource>" builder affordances: warehouse/database/role
    # are name-keyed (the picker stores the name, which the create op takes as
    # input), so the create ops carry no x-resource-id-path — the affordance
    # still surfaces (it needs only x-creates-resource + x-resource-type) and the
    # builder fills the field with the name it created.
    _DROPDOWN_RESOURCE_TYPES: Dict[str, str] = {
        "warehouse": "snowflake_warehouse",
        "database": "snowflake_database",
        "role": "snowflake_role",
    }

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        schema = super().get_config_schema()

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    for fschema in props.values():
                        if isinstance(fschema, dict):
                            dyn = fschema.get("x-dynamic-options")
                            if isinstance(dyn, dict):
                                rt = cls._DROPDOWN_RESOURCE_TYPES.get(dyn.get("field_name"))
                                if rt and "x-resource-type" not in fschema:
                                    fschema["x-resource-type"] = rt
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
        return schema

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """Operation-aware override for this mixed action+trigger node: the poll
        trigger returns None (the webhook POST is a wake-up signal, so execute()
        runs the query), while any other op keeps the default passthrough. The
        mixin's blanket-None is only right for trigger-only nodes."""
        if config.get("operation") == "on_query_results":
            return None
        return payload

    async def _request(
        self,
        account_identifier: str,
        token: str,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Instance wrapper that injects the per-credential token type."""
        return await _snowflake_request(
            account_identifier,
            token,
            method,
            endpoint,
            params=params,
            json_body=json_body,
            action_name=action_name,
            token_type=self._token_type,
        )

    # ------------------------------------------------------------------
    # Dynamic options (databases / warehouses / roles)
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
        endpoints = {
            "warehouse": "/warehouses",
            "database": "/databases",
            "name": "/databases",  # used by fetch/delete database + warehouse ops
            "role": "/roles",
        }
        endpoint = endpoints.get(field_name)
        if not endpoint or not credential_data:
            return {"options": []}

        result = await _snowflake_request(
            credential_data.get("account_identifier"),
            credential_data.get("token"),
            "GET",
            endpoint,
            action_name=f"list{endpoint}",
            token_type="PROGRAMMATIC_ACCESS_TOKEN",
        )
        if result.get("status") != "success":
            return {"options": []}
        rows = result.get("data") or []
        if not isinstance(rows, list):
            rows = rows.get("data") if isinstance(rows, dict) else []
        options = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if name:
                options.append({"label": str(name), "value": str(name)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, SnowflakeNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Snowflake account identifier and token."
            )

        account = credentials.account_identifier
        token = credentials.token

        handlers = {
            "run_statement": self._run_statement,
            "get_statement": self._get_statement,
            "cancel_statement": self._cancel_statement,
            "list_databases": self._list_databases,
            "create_database": self._create_database,
            "fetch_database": self._fetch_database,
            "delete_database": self._delete_database,
            "list_schemas": self._list_schemas,
            "list_tables": self._list_tables,
            "fetch_table": self._fetch_table,
            "list_warehouses": self._list_warehouses,
            "create_warehouse": self._create_warehouse,
            "resume_warehouse": self._resume_warehouse,
            "suspend_warehouse": self._suspend_warehouse,
            "abort_warehouse": self._abort_warehouse,
            "list_tasks": self._list_tasks,
            "create_task": self._create_task,
            "execute_task": self._execute_task,
            "resume_task": self._resume_task,
            "suspend_task": self._suspend_task,
            "task_history": self._task_history,
            "list_users": self._list_users,
            "create_user": self._create_user,
            "delete_user": self._delete_user,
            "list_roles": self._list_roles,
            "list_stages": self._list_stages,
            "on_query_results": self._on_query_results,
        }
        handler = handlers.get(op.operation)
        if handler:
            result = await handler(op, account, token)
        else:
            # Generated control-plane ops: module-level handlers taking the node
            # as first arg so they reuse self._request (token-type injection).
            gen_handler = SNOWFLAKE_OPERATION_HANDLERS.get(op.operation)
            if not gen_handler:
                raise ValueError(f"Unknown operation: {op.operation}")
            result = await gen_handler(self, op, account, token)

        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # SQL handlers
    # ------------------------------------------------------------------
    async def _run_statement(
        self, c: SnowflakeRunStatementConfig, account: str, token: str
    ) -> Dict[str, Any]:
        body = {
            "statement": c.statement,
            "warehouse": c.warehouse,
            "database": c.database,
            "schema": c.schema_name,
            "role": c.role,
            "timeout": int(c.timeout) if c.timeout and str(c.timeout).isdigit() else None,
        }
        params = {"async": "true"} if str(c.run_async).lower() == "true" else None
        return await self._request(
            account, token, "POST", "/statements", params=params,
            json_body=body, action_name="run_statement",
        )

    async def _get_statement(
        self, c: SnowflakeGetStatementConfig, account: str, token: str
    ) -> Dict[str, Any]:
        params = {"partition": c.partition} if c.partition not in (None, "") else None
        return await self._request(
            account, token, "GET", f"/statements/{c.statement_handle}",
            params=params, action_name="get_statement",
        )

    async def _cancel_statement(
        self, c: SnowflakeCancelStatementConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST", f"/statements/{c.statement_handle}/cancel",
            action_name="cancel_statement",
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    @staticmethod
    def _rows_to_dicts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map the SQL API's array-of-arrays `data` into a list of dicts keyed by
        column name (from resultSetMetaData.rowType). Falls back to positional
        `col0..` keys if metadata is absent."""
        rows = data.get("data") or []
        if not isinstance(rows, list):
            return []
        row_type = (data.get("resultSetMetaData") or {}).get("rowType") or []
        columns = [str(col.get("name")) for col in row_type if isinstance(col, dict)]
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list):
                continue
            if columns and len(columns) == len(row):
                out.append(dict(zip(columns, row)))
            else:
                out.append({f"col{i}": v for i, v in enumerate(row)})
        return out

    async def _on_query_results(
        self, c: "SnowflakeOnQueryResultsConfig", account: str, token: str
    ) -> Dict[str, Any]:
        """Run the user query, emit only rows whose cursor value is greater than
        the last seen value, and advance the persisted cursor.

        The cursor high-water-mark is stored in node state (workflow_node_state),
        scoped to (workflow_id, node_id), so it survives across headless polls —
        mutating config in-memory here would be discarded and re-emit every row.
        The FIRST poll *baselines*: it records the current high-water-mark and
        emits nothing, so enabling the trigger never floods the workflow with
        the entire existing result set — it only fires for rows added afterwards.
        """
        body = {
            "statement": c.statement,
            "warehouse": c.warehouse,
            "database": c.database,
            "schema": c.schema_name,
            "role": c.role,
        }
        result = await self._request(
            account, token, "POST", "/statements", json_body=body,
            action_name="on_query_results",
        )
        if result.get("status") != "success":
            return result

        all_rows = self._rows_to_dicts(result.get("data") or {})
        cursor_col = c.cursor_column

        def mutator(state):
            is_first_poll = "last_seen_cursor" not in state
            last_seen = state.get("last_seen_cursor")

            new_items: List[Dict[str, Any]] = []
            max_cursor = last_seen
            for row in all_rows:
                value = row.get(cursor_col)
                if value is None:
                    continue
                cursor_str = str(value)
                # String compare: Snowflake returns scalars as strings; ISO
                # timestamps and zero-padded ids order lexicographically.
                if not is_first_poll and (last_seen is None or cursor_str > last_seen):
                    new_items.append(row)
                if max_cursor is None or cursor_str > max_cursor:
                    max_cursor = cursor_str

            if max_cursor is None:
                # No usable cursor value yet (empty result, or the cursor column
                # is null on every row). Stay UNBASELINED — persisting a null
                # high-water-mark would make the next poll treat every row as new
                # (last_seen is None ⇒ everything qualifies) and flood.
                return None, (new_items, max_cursor)
            if is_first_poll or max_cursor != last_seen:
                return {"last_seen_cursor": max_cursor}, (new_items, max_cursor)
            return None, (new_items, max_cursor)  # nothing new → no write

        new_items, max_cursor = await self._update_node_state(
            mutator, skip_result=([], None)
        )

        # Drive the mixin's trigger_produced_no_event skip: nothing new → the
        # executor halts downstream instead of firing on an empty result.
        self._poll_emitted_count = len(new_items)

        return {
            "status": "success",
            "action": "on_query_results",
            "operation": "on_query_results",
            "items": new_items,
            "new_count": len(new_items),
            "cursor_column": cursor_col,
            "last_seen_cursor": max_cursor,
            "timing_ms": result.get("timing_ms", {}),
        }

    # ------------------------------------------------------------------
    # Database handlers
    # ------------------------------------------------------------------
    async def _list_databases(
        self, c: SnowflakeListDatabasesConfig, account: str, token: str
    ) -> Dict[str, Any]:
        params = {"like": c.like, "startsWith": c.starts_with, "showLimit": c.show_limit}
        return await self._request(
            account, token, "GET", "/databases", params=params,
            action_name="list_databases",
        )

    async def _create_database(
        self, c: SnowflakeCreateDatabaseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        body = {"name": c.name, "comment": c.comment}
        return await self._request(
            account, token, "POST", "/databases", json_body=body,
            action_name="create_database",
        )

    async def _fetch_database(
        self, c: SnowflakeFetchDatabaseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET", f"/databases/{c.name}",
            action_name="fetch_database",
        )

    async def _delete_database(
        self, c: SnowflakeDeleteDatabaseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "DELETE", f"/databases/{c.name}",
            action_name="delete_database",
        )

    # ------------------------------------------------------------------
    # Schema / Table handlers
    # ------------------------------------------------------------------
    async def _list_schemas(
        self, c: SnowflakeListSchemasConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET", f"/databases/{c.database}/schemas",
            params={"like": c.like}, action_name="list_schemas",
        )

    async def _list_tables(
        self, c: SnowflakeListTablesConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET",
            f"/databases/{c.database}/schemas/{c.schema_name}/tables",
            params={"like": c.like}, action_name="list_tables",
        )

    async def _fetch_table(
        self, c: SnowflakeFetchTableConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET",
            f"/databases/{c.database}/schemas/{c.schema_name}/tables/{c.name}",
            action_name="fetch_table",
        )

    # ------------------------------------------------------------------
    # Warehouse handlers
    # ------------------------------------------------------------------
    async def _list_warehouses(
        self, c: SnowflakeListWarehousesConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET", "/warehouses", params={"like": c.like},
            action_name="list_warehouses",
        )

    async def _create_warehouse(
        self, c: SnowflakeCreateWarehouseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "warehouse_size": c.warehouse_size,
            "auto_suspend": int(c.auto_suspend)
            if c.auto_suspend and str(c.auto_suspend).isdigit()
            else None,
        }
        return await self._request(
            account, token, "POST", "/warehouses", json_body=body,
            action_name="create_warehouse",
        )

    async def _resume_warehouse(
        self, c: SnowflakeResumeWarehouseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST", f"/warehouses/{c.name}:resume",
            action_name="resume_warehouse",
        )

    async def _suspend_warehouse(
        self, c: SnowflakeSuspendWarehouseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST", f"/warehouses/{c.name}:suspend",
            action_name="suspend_warehouse",
        )

    async def _abort_warehouse(
        self, c: SnowflakeAbortWarehouseConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST", f"/warehouses/{c.name}:abort",
            action_name="abort_warehouse",
        )

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------
    async def _list_tasks(
        self, c: SnowflakeListTasksConfig, account: str, token: str
    ) -> Dict[str, Any]:
        params = {"rootOnly": "true"} if str(c.root_only).lower() == "true" else None
        return await self._request(
            account, token, "GET",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks",
            params=params, action_name="list_tasks",
        )

    async def _create_task(
        self, c: SnowflakeCreateTaskConfig, account: str, token: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "definition": c.definition,
            "warehouse": c.warehouse,
            "schedule": _sf_task_schedule(c.task_schedule),
        }
        return await self._request(
            account, token, "POST",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks",
            json_body=body, action_name="create_task",
        )

    async def _execute_task(
        self, c: SnowflakeExecuteTaskConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:execute",
            action_name="execute_task",
        )

    async def _resume_task(
        self, c: SnowflakeResumeTaskConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:resume",
            action_name="resume_task",
        )

    async def _suspend_task(
        self, c: SnowflakeSuspendTaskConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "POST",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}:suspend",
            action_name="suspend_task",
        )

    async def _task_history(
        self, c: SnowflakeTaskHistoryConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET",
            f"/databases/{c.database}/schemas/{c.schema_name}/tasks/{c.name}/complete-graphs",
            action_name="task_history",
        )

    # ------------------------------------------------------------------
    # User / Role handlers
    # ------------------------------------------------------------------
    async def _list_users(
        self, c: SnowflakeListUsersConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET", "/users", params={"like": c.like},
            action_name="list_users",
        )

    async def _create_user(
        self, c: SnowflakeCreateUserConfig, account: str, token: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "email": c.email,
            "default_role": c.default_role,
        }
        return await self._request(
            account, token, "POST", "/users", json_body=body,
            action_name="create_user",
        )

    async def _delete_user(
        self, c: SnowflakeDeleteUserConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "DELETE", f"/users/{c.name}",
            action_name="delete_user",
        )

    async def _list_roles(
        self, c: SnowflakeListRolesConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET", "/roles", params={"like": c.like},
            action_name="list_roles",
        )

    # ------------------------------------------------------------------
    # Stage handler
    # ------------------------------------------------------------------
    async def _list_stages(
        self, c: SnowflakeListStagesConfig, account: str, token: str
    ) -> Dict[str, Any]:
        return await self._request(
            account, token, "GET",
            f"/databases/{c.database}/schemas/{c.schema_name}/stages",
            params={"like": c.like}, action_name="list_stages",
        )
