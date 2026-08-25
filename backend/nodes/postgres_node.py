"""
PostgreSQL database automation node.

Provides workflow integration with PostgreSQL databases for operations including:
- Query: Execute SELECT queries and return results
- Execute: Run INSERT/UPDATE/DELETE statements
- List Tables: Get all tables in a schema
- List Columns: Get column metadata for a table

Authentication: Connection string (recommended) or individual credentials
Library: asyncpg for high-performance async queries
Documentation: https://magicstack.github.io/asyncpg/current/
"""

import asyncio
import logging
import ssl
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import parse_qsl, unquote, urlsplit
from pydantic import BaseModel, Field, Discriminator
import asyncpg

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import SSRFError, resolve_host_addresses

logger = logging.getLogger(__name__)


class _PinnedPostgresLoop:
    """Event-loop proxy that dials one validated IP for one PostgreSQL host.

    Asyncpg must still receive the original hostname so ``verify-full`` and
    TLS SNI work. It stores that hostname in its protocol and passes it to
    ``start_tls``; only the initial TCP ``create_connection`` call is rewritten
    to the already-validated IP. Direct TLS gets an explicit original
    ``server_hostname`` before the dial target is replaced.
    """

    def __init__(self, loop, host: str, port: int, address: str):
        self._loop = loop
        self._host = host
        self._normalized_host = host.lower().rstrip(".")
        self._port = port
        self._address = address

    def __getattr__(self, name):
        return getattr(self._loop, name)

    async def create_connection(
        self,
        protocol_factory,
        host=None,
        port=None,
        *args,
        **kwargs,
    ):
        normalized_host = str(host or "").lower().rstrip(".")
        if normalized_host != self._normalized_host or port != self._port:
            raise SSRFError("PostgreSQL driver attempted an unvalidated connection target")
        if kwargs.get("ssl") and "server_hostname" not in kwargs:
            kwargs["server_hostname"] = self._host
        return await self._loop.create_connection(
            protocol_factory,
            self._address,
            port,
            *args,
            **kwargs,
        )


async def _connect_pinned_postgres(
    host: str,
    port: int,
    **connect_kwargs,
) -> asyncpg.Connection:
    """Resolve once, then make asyncpg dial only a validated address."""
    addresses = await resolve_host_addresses(host, port)
    loop = asyncio.get_running_loop()
    last_error: Optional[OSError] = None
    for address in addresses:
        pinned_loop = _PinnedPostgresLoop(loop, host, port, address)
        try:
            return await asyncpg.connect(
                host=host,
                port=port,
                loop=pinned_loop,
                direct_tls=False,
                statement_cache_size=0,
                target_session_attrs="any",
                **connect_kwargs,
            )
        except OSError as error:
            last_error = error
    if last_error is not None:
        raise last_error
    raise SSRFError("PostgreSQL host did not resolve to an allowed address")


_SAFE_DSN_QUERY_FIELDS = {"sslmode", "application_name"}
_SAFE_SSL_MODES = {"disable", "require", "verify-ca", "verify-full"}


def _postgres_ssl_context(mode: Optional[str]):
    """Build SSL behavior without asyncpg consulting PG* files or defaults."""
    normalized = str(mode or "require").strip().lower()
    if normalized not in _SAFE_SSL_MODES:
        raise SSRFError(
            "PostgreSQL SSL mode must be disable, require, verify-ca, or verify-full"
        )
    if normalized == "disable":
        return False
    if normalized == "require":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    context = ssl.create_default_context()
    if normalized == "verify-ca":
        context.check_hostname = False
    return context


def _parse_safe_postgres_dsn(connection_string: str) -> Dict[str, Any]:
    """Parse a DSN into explicit asyncpg args without ambient credential IO."""
    try:
        parts = urlsplit(connection_string)
        port = parts.port or 5432
    except ValueError as error:
        raise SSRFError("PostgreSQL connection string is invalid") from error
    if parts.scheme not in {"postgres", "postgresql"} or not parts.hostname:
        raise SSRFError(
            "PostgreSQL connection string must be a postgres:// URL with a host"
        )
    if "," in parts.hostname or parts.hostname.startswith("/"):
        raise SSRFError("PostgreSQL connection strings must use one TCP host")
    if parts.fragment:
        raise SSRFError("PostgreSQL connection strings must not contain a fragment")
    if parts.username is None or parts.password is None:
        raise SSRFError(
            "PostgreSQL connection strings must include an explicit username and password"
        )

    try:
        query_items = parse_qsl(
            parts.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as error:
        raise SSRFError("PostgreSQL connection string query is invalid") from error
    query: Dict[str, str] = {}
    for key, value in query_items:
        normalized_key = key.lower()
        if normalized_key not in _SAFE_DSN_QUERY_FIELDS:
            raise SSRFError(
                f"PostgreSQL connection option '{key}' is not allowed"
            )
        if normalized_key in query:
            raise SSRFError(
                f"PostgreSQL connection option '{key}' must not be repeated"
            )
        query[normalized_key] = value

    username = unquote(parts.username)
    password = unquote(parts.password)
    if not username or not password:
        raise SSRFError(
            "PostgreSQL connection strings must include a non-empty username and password"
        )
    database = unquote(parts.path.lstrip("/")) or username
    server_settings = {}
    if query.get("application_name"):
        server_settings["application_name"] = query["application_name"]
    return {
        "host": parts.hostname,
        "port": port,
        "database": database,
        "user": username,
        "password": password,
        "ssl": _postgres_ssl_context(query.get("sslmode")),
        "server_settings": server_settings or None,
    }


# ============================================================================
# Credential Schema
# ============================================================================


class PostgresConnectionStringCredential(BaseModel):
    """
    Connection string credential for PostgreSQL.

    Format: postgresql://user:password@host:port/database
    Can also include SSL mode: ?sslmode=require

    Example: postgresql://myuser:mypassword@localhost:5432/mydb
    """

    credential_type: Literal["postgres_connection_string"] = Field(
        "postgres_connection_string", json_schema_extra={"ui:hidden": True}
    )
    connection_string: str = Field(
        ...,
        title="Connection String",
        description="PostgreSQL connection string (e.g., postgresql://user:password@host:port/database)",
        json_schema_extra={
            "ui:widget": "password",
            "placeholder": "postgresql://user:password@host:port/database",
        },
    )


class PostgresCredentialsCredential(BaseModel):
    """
    Individual credentials for PostgreSQL connection.

    Use this when you prefer to specify each connection parameter separately.
    """

    credential_type: Literal["postgres_credentials"] = Field(
        "postgres_credentials", json_schema_extra={"ui:hidden": True}
    )
    host: str = Field(
        ...,
        title="Host",
        description="PostgreSQL server hostname or IP address",
        json_schema_extra={"placeholder": "localhost"},
    )
    port: int = Field(
        5432,
        title="Port",
        description="PostgreSQL server port (default: 5432)",
        ge=1,
        le=65535,
    )
    database: str = Field(
        ...,
        title="Database",
        description="Name of the database to connect to",
        json_schema_extra={"placeholder": "mydb"},
    )
    user: str = Field(..., title="Username", description="PostgreSQL username")
    password: str = Field(
        ...,
        title="Password",
        description="PostgreSQL password",
        json_schema_extra={"ui:widget": "password"},
    )
    ssl_mode: Optional[str] = Field(
        None,
        title="SSL Mode",
        description="SSL connection mode (defaults to require)",
        json_schema_extra={
            "enum": [
                "disable",
                "require",
                "verify-ca",
                "verify-full",
            ]
        },
    )


# Union type for credentials - connection string first (recommended)
PostgresCredential = Union[
    PostgresConnectionStringCredential, PostgresCredentialsCredential
]


# ============================================================================
# Operation Configs
# ============================================================================


class PostgresQueryConfig(BaseModel):
    """Execute a SELECT query and return results as JSON"""

    operation: Literal["run_select_query"] = Field(
        "run_select_query",
        json_schema_extra={
            "const": "run_select_query",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Run Select Query",
            "x-keywords": [
                "run sql",
                "select rows",
                "query database",
                "fetch records",
                "raw sql",
                "read data",
            ],
        },
        title="Run Select Query",
    )
    query: str = Field(
        ...,
        title="SQL Query",
        description="SELECT query to execute. Use $1, $2, etc. for parameters.",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "SELECT * FROM users WHERE id = $1",
        },
    )
    params: Optional[List[Any]] = Field(
        None,
        title="Query Parameters",
        description="Parameters to safely substitute into query ($1, $2, etc.). Pass as JSON array.",
    )
    limit: Optional[int] = Field(
        1000,
        title="Row Limit",
        description="Maximum number of rows to return (default: 1000, max: 10000)",
        ge=1,
        le=10000,
    )


class PostgresExecuteConfig(BaseModel):
    """Execute an INSERT, UPDATE, DELETE, or other non-SELECT statement"""

    operation: Literal["execute_sql_statement"] = Field(
        "execute_sql_statement",
        json_schema_extra={
            "const": "execute_sql_statement",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Execute Sql Statement",
            "x-keywords": [
                "insert row",
                "update rows",
                "write sql",
                "run statement",
                "modify data",
                "non select",
            ],
        },
        title="Execute Sql Statement",
    )
    statement: str = Field(
        ...,
        title="SQL Statement",
        description="SQL statement to execute. Use $1, $2, etc. for parameters.",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "INSERT INTO users (name, email) VALUES ($1, $2)",
        },
    )
    params: Optional[List[Any]] = Field(
        None,
        title="Statement Parameters",
        description="Parameters to safely substitute into statement ($1, $2, etc.). Pass as JSON array.",
    )
    return_rows: Optional[bool] = Field(
        False,
        title="Return Rows",
        description="For statements with RETURNING clause, return the rows",
    )


class PostgresExecuteManyConfig(BaseModel):
    """Execute a statement with multiple parameter sets (batch operations)"""

    operation: Literal["execute_batch_statements"] = Field(
        "execute_batch_statements",
        json_schema_extra={
            "const": "execute_batch_statements",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Execute Batch Statements",
            "x-keywords": [
                "bulk insert",
                "batch write",
                "multiple inserts",
                "many parameter sets",
                "bulk statements",
            ],
        },
        title="Execute Batch Statements",
    )
    statement: str = Field(
        ...,
        title="SQL Statement",
        description="SQL statement to execute for each parameter set",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "INSERT INTO users (name, email) VALUES ($1, $2)",
        },
    )
    params_list: List[List[Any]] = Field(
        ...,
        title="Parameter Sets",
        description="List of parameter arrays. Each inner array is one execution.",
    )


class PostgresListTablesConfig(BaseModel):
    """List all tables in a schema"""

    operation: Literal["list_schema_tables"] = Field(
        "list_schema_tables",
        json_schema_extra={
            "const": "list_schema_tables",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Schema Tables",
            "x-keywords": [
                "show tables",
                "all tables",
                "tables in schema",
                "table names",
            ],
        },
        title="List Schema Tables",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list tables from (default: public)",
    )
    include_views: Optional[bool] = Field(
        False, title="Include Views", description="Include views in the results"
    )


class PostgresListColumnsConfig(BaseModel):
    """Get column metadata for a table"""

    operation: Literal["list_table_columns"] = Field(
        "list_table_columns",
        json_schema_extra={
            "const": "list_table_columns",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Table Columns",
            "x-keywords": [
                "column metadata",
                "table columns",
                "describe columns",
                "show fields",
                "schema of table",
            ],
        },
        title="List Table Columns",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to get columns for"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


class PostgresGetTableInfoConfig(BaseModel):
    """Get detailed information about a table including constraints and indexes"""

    operation: Literal["get_table_info"] = Field(
        "get_table_info",
        json_schema_extra={
            "const": "get_table_info",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Get Table Info",
            "x-keywords": [
                "describe table",
                "table details",
                "table structure",
                "constraints and indexes",
                "inspect table",
            ],
        },
        title="Get Table Info",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to get information for"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


# ============================================================================
# Schema Management Configs
# ============================================================================


class PostgresListSchemasConfig(BaseModel):
    """List all schemas in the database"""

    operation: Literal["list_schemas"] = Field(
        "list_schemas",
        json_schema_extra={
            "const": "list_schemas",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "List Schemas",
            "x-keywords": ["show schemas", "all schemas", "namespaces", "schema names"],
        },
        title="List Schemas",
    )


class PostgresCreateSchemaConfig(BaseModel):
    """Create a new schema"""

    operation: Literal["create_schema"] = Field(
        "create_schema",
        json_schema_extra={
            "const": "create_schema",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "Create Schema",
            "x-keywords": ["new schema", "make schema", "add namespace"],
        },
        title="Create Schema",
    )
    schema_name: str = Field(
        ..., title="Schema Name", description="Name of the schema to create"
    )
    if_not_exists: Optional[bool] = Field(
        True,
        title="If Not Exists",
        description="Only create if schema doesn't already exist",
    )


class PostgresDropSchemaConfig(BaseModel):
    """Drop a schema"""

    operation: Literal["drop_schema"] = Field(
        "drop_schema",
        json_schema_extra={
            "const": "drop_schema",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "Drop Schema",
            "x-keywords": ["delete schema", "remove schema", "drop namespace"],
        },
        title="Drop Schema",
    )
    schema_name: str = Field(
        ..., title="Schema Name", description="Name of the schema to drop"
    )
    cascade: Optional[bool] = Field(
        False,
        title="Cascade",
        description="Automatically drop objects contained in the schema",
    )
    if_exists: Optional[bool] = Field(
        True,
        title="If Exists",
        description="Only drop if schema exists (avoids errors)",
    )


# ============================================================================
# Database Management Configs
# ============================================================================


class PostgresListDatabasesConfig(BaseModel):
    """List all databases in the PostgreSQL server"""

    operation: Literal["list_databases"] = Field(
        "list_databases",
        json_schema_extra={
            "const": "list_databases",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "List Databases",
            "x-keywords": [
                "show databases",
                "all databases",
                "list dbs",
                "database names",
            ],
        },
        title="List Databases",
    )


# ============================================================================
# Index Management Configs
# ============================================================================


class PostgresListIndexesConfig(BaseModel):
    """List all indexes in a schema"""

    operation: Literal["list_schema_indexes"] = Field(
        "list_schema_indexes",
        json_schema_extra={
            "const": "list_schema_indexes",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "List Schema Indexes",
            "x-keywords": ["show indexes", "all indexes", "list indexes"],
        },
        title="List Schema Indexes",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list indexes from (default: public)",
    )
    table_name: Optional[str] = Field(
        None,
        title="Table Name (Optional)",
        description="Filter indexes for a specific table",
    )


class PostgresCreateIndexConfig(BaseModel):
    """Create an index on a table"""

    operation: Literal["create_index"] = Field(
        "create_index",
        json_schema_extra={
            "const": "create_index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Create Index",
            "x-keywords": ["new index", "add index", "make index", "index column"],
        },
        title="Create Index",
    )
    index_name: str = Field(
        ..., title="Index Name", description="Name of the index to create"
    )
    table_name: str = Field(
        ..., title="Table Name", description="Table to create the index on"
    )
    columns: List[str] = Field(
        ..., title="Columns", description="List of column names to index"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )
    unique: Optional[bool] = Field(
        False, title="Unique", description="Create a unique index"
    )
    if_not_exists: Optional[bool] = Field(
        True, title="If Not Exists", description="Only create if index doesn't exist"
    )


class PostgresDropIndexConfig(BaseModel):
    """Drop an index"""

    operation: Literal["drop_index"] = Field(
        "drop_index",
        json_schema_extra={
            "const": "drop_index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Drop Index",
            "x-keywords": ["delete index", "remove index"],
        },
        title="Drop Index",
    )
    index_name: str = Field(
        ..., title="Index Name", description="Name of the index to drop"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the index (default: public)",
    )
    if_exists: Optional[bool] = Field(
        True, title="If Exists", description="Only drop if index exists"
    )


# ============================================================================
# View Management Configs
# ============================================================================


class PostgresListViewsConfig(BaseModel):
    """List all views in a schema"""

    operation: Literal["list_schema_views"] = Field(
        "list_schema_views",
        json_schema_extra={
            "const": "list_schema_views",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "List Schema Views",
            "x-keywords": ["show views", "all views", "list views"],
        },
        title="List Schema Views",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list views from (default: public)",
    )


class PostgresCreateViewConfig(BaseModel):
    """Create a view"""

    operation: Literal["create_view"] = Field(
        "create_view",
        json_schema_extra={
            "const": "create_view",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Create View",
            "x-keywords": ["new view", "make view", "add view", "define view"],
        },
        title="Create View",
    )
    view_name: str = Field(
        ..., title="View Name", description="Name of the view to create"
    )
    query: str = Field(
        ...,
        title="SELECT Query",
        description="SELECT query that defines the view",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "SELECT column1, column2 FROM table_name WHERE condition",
        },
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema to create the view in (default: public)",
    )
    or_replace: Optional[bool] = Field(
        False, title="Or Replace", description="Replace the view if it already exists"
    )


class PostgresDropViewConfig(BaseModel):
    """Drop a view"""

    operation: Literal["drop_view"] = Field(
        "drop_view",
        json_schema_extra={
            "const": "drop_view",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Drop View",
            "x-keywords": ["delete view", "remove view"],
        },
        title="Drop View",
    )
    view_name: str = Field(
        ..., title="View Name", description="Name of the view to drop"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the view (default: public)",
    )
    if_exists: Optional[bool] = Field(
        True, title="If Exists", description="Only drop if view exists"
    )


# ============================================================================
# Sequence Management Configs
# ============================================================================


class PostgresListSequencesConfig(BaseModel):
    """List all sequences in a schema"""

    operation: Literal["list_schema_sequences"] = Field(
        "list_schema_sequences",
        json_schema_extra={
            "const": "list_schema_sequences",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "List Schema Sequences",
            "x-keywords": ["show sequences", "all sequences", "list sequences"],
        },
        title="List Schema Sequences",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list sequences from (default: public)",
    )


class PostgresGetNextSequenceValueConfig(BaseModel):
    """Get the next value from a sequence (nextval)"""

    operation: Literal["get_sequence_next_value"] = Field(
        "get_sequence_next_value",
        json_schema_extra={
            "const": "get_sequence_next_value",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "Get Sequence Next Value",
            "x-keywords": [
                "next id",
                "nextval",
                "advance sequence",
                "increment sequence",
                "next sequence value",
            ],
        },
        title="Get Sequence Next Value",
    )
    sequence_name: str = Field(
        ..., title="Sequence Name", description="Name of the sequence"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the sequence (default: public)",
    )


class PostgresGetCurrentSequenceValueConfig(BaseModel):
    """Get the current value from a sequence (currval)"""

    operation: Literal["get_sequence_current_value"] = Field(
        "get_sequence_current_value",
        json_schema_extra={
            "const": "get_sequence_current_value",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "Get Sequence Current Value",
            "x-keywords": [
                "currval",
                "current id",
                "current sequence value",
                "last sequence value",
            ],
        },
        title="Get Sequence Current Value",
    )
    sequence_name: str = Field(
        ..., title="Sequence Name", description="Name of the sequence"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the sequence (default: public)",
    )


class PostgresSetSequenceValueConfig(BaseModel):
    """Set the current value of a sequence (setval)"""

    operation: Literal["set_sequence_value"] = Field(
        "set_sequence_value",
        json_schema_extra={
            "const": "set_sequence_value",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "Set Sequence Value",
            "x-keywords": [
                "setval",
                "reset sequence",
                "set counter",
                "set sequence number",
            ],
        },
        title="Set Sequence Value",
    )
    sequence_name: str = Field(
        ..., title="Sequence Name", description="Name of the sequence"
    )
    value: int = Field(..., title="Value", description="Value to set the sequence to")
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the sequence (default: public)",
    )
    is_called: Optional[bool] = Field(
        True,
        title="Is Called",
        description="If true, next nextval will advance before returning; if false, next nextval returns this value",
    )


# ============================================================================
# Function/Procedure Configs
# ============================================================================


class PostgresListFunctionsConfig(BaseModel):
    """List all functions in a schema"""

    operation: Literal["list_schema_functions"] = Field(
        "list_schema_functions",
        json_schema_extra={
            "const": "list_schema_functions",
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "List Schema Functions",
            "x-keywords": [
                "show functions",
                "all functions",
                "list functions",
                "stored procedures",
            ],
        },
        title="List Schema Functions",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list functions from (default: public)",
    )


class PostgresCallFunctionConfig(BaseModel):
    """Call a PostgreSQL function"""

    operation: Literal["call_database_function"] = Field(
        "call_database_function",
        json_schema_extra={
            "const": "call_database_function",
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "Call Database Function",
            "x-keywords": [
                "call function",
                "run function",
                "invoke function",
                "execute procedure",
                "call stored procedure",
            ],
        },
        title="Call Database Function",
    )
    function_name: str = Field(
        ..., title="Function Name", description="Name of the function to call"
    )
    params: Optional[List[Any]] = Field(
        None,
        title="Function Parameters",
        description="Parameters to pass to the function. Pass as JSON array.",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the function (default: public)",
    )


# ============================================================================
# Constraint Management Configs
# ============================================================================


class PostgresListConstraintsConfig(BaseModel):
    """List all constraints for a table"""

    operation: Literal["list_table_constraints"] = Field(
        "list_table_constraints",
        json_schema_extra={
            "const": "list_table_constraints",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Table Constraints",
            "x-keywords": [
                "show constraints",
                "foreign keys",
                "primary keys",
                "table constraints",
                "check constraints",
            ],
        },
        title="List Table Constraints",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to list constraints for"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


# ============================================================================
# Trigger Management Configs
# ============================================================================


class PostgresListTriggersConfig(BaseModel):
    """List all triggers in a schema"""

    operation: Literal["list_schema_triggers"] = Field(
        "list_schema_triggers",
        json_schema_extra={
            "const": "list_schema_triggers",
            "ui:hidden": True,
            "x-category": "Trigger",
            "x-is-trigger": False,
            "x-display-name": "List Schema Triggers",
            "x-keywords": [
                "show triggers",
                "all triggers",
                "list triggers",
                "db triggers",
            ],
        },
        title="List Schema Triggers",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema name to list triggers from (default: public)",
    )
    table_name: Optional[str] = Field(
        None,
        title="Table Name (Optional)",
        description="Filter triggers for a specific table",
    )


# ============================================================================
# Extension Management Configs
# ============================================================================


class PostgresListExtensionsConfig(BaseModel):
    """List all installed extensions"""

    operation: Literal["list_extensions"] = Field(
        "list_extensions",
        json_schema_extra={
            "const": "list_extensions",
            "ui:hidden": True,
            "x-category": "Extension",
            "x-is-trigger": False,
            "x-display-name": "List Extensions",
            "x-keywords": [
                "show extensions",
                "installed extensions",
                "list extensions",
            ],
        },
        title="List Extensions",
    )


class PostgresCreateExtensionConfig(BaseModel):
    """Create/install an extension"""

    operation: Literal["install_extension"] = Field(
        "install_extension",
        json_schema_extra={
            "const": "install_extension",
            "ui:hidden": True,
            "x-category": "Extension",
            "x-is-trigger": False,
            "x-display-name": "Install Extension",
            "x-keywords": [
                "enable extension",
                "add extension",
                "create extension",
                "install pgvector",
            ],
        },
        title="Install Extension",
    )
    extension_name: str = Field(
        ...,
        title="Extension Name",
        description="Name of the extension to create (e.g., 'uuid-ossp', 'pg_trgm')",
    )
    schema_name: Optional[str] = Field(
        None,
        title="Schema (Optional)",
        description="Schema to create extension in (default: depends on extension)",
    )
    if_not_exists: Optional[bool] = Field(
        True,
        title="If Not Exists",
        description="Only create if extension doesn't exist",
    )


# ============================================================================
# Table Management Configs
# ============================================================================


class PostgresCreateTableConfig(BaseModel):
    """Create a new table"""

    operation: Literal["create_table"] = Field(
        "create_table",
        json_schema_extra={
            "const": "create_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Create Table",
            "x-keywords": [
                "new table",
                "make table",
                "define table",
                "add table",
                "create relation",
            ],
        },
        title="Create Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to create"
    )
    columns: str = Field(
        ...,
        title="Column Definitions",
        description="Column definitions (e.g., 'id SERIAL PRIMARY KEY, name TEXT NOT NULL')",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "id SERIAL PRIMARY KEY,\nname TEXT NOT NULL,\nemail TEXT UNIQUE",
        },
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema to create the table in (default: public)",
    )
    if_not_exists: Optional[bool] = Field(
        True, title="If Not Exists", description="Only create if table doesn't exist"
    )


class PostgresDropTableConfig(BaseModel):
    """Drop a table"""

    operation: Literal["drop_table"] = Field(
        "drop_table",
        json_schema_extra={
            "const": "drop_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Drop Table",
            "x-keywords": ["delete table", "remove table", "drop relation"],
        },
        title="Drop Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to drop"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )
    cascade: Optional[bool] = Field(
        False,
        title="Cascade",
        description="Automatically drop objects that depend on the table",
    )
    if_exists: Optional[bool] = Field(
        True, title="If Exists", description="Only drop if table exists"
    )


class PostgresTruncateTableConfig(BaseModel):
    """Truncate a table (remove all rows)"""

    operation: Literal["truncate_table"] = Field(
        "truncate_table",
        json_schema_extra={
            "const": "truncate_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Truncate Table",
            "x-keywords": [
                "empty table",
                "clear all rows",
                "wipe table",
                "delete all rows",
            ],
        },
        title="Truncate Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to truncate"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )
    restart_identity: Optional[bool] = Field(
        False,
        title="Restart Identity",
        description="Restart sequences owned by columns of the truncated table",
    )
    cascade: Optional[bool] = Field(
        False,
        title="Cascade",
        description="Automatically truncate tables with foreign key references",
    )


# ============================================================================
# User/Role Management Configs
# ============================================================================


class PostgresListUsersConfig(BaseModel):
    """List all database users"""

    operation: Literal["list_database_users"] = Field(
        "list_database_users",
        json_schema_extra={
            "const": "list_database_users",
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "List Database Users",
            "x-keywords": ["show users", "all users", "db users", "list accounts"],
        },
        title="List Database Users",
    )


class PostgresListRolesConfig(BaseModel):
    """List all database roles"""

    operation: Literal["list_database_roles"] = Field(
        "list_database_roles",
        json_schema_extra={
            "const": "list_database_roles",
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "List Database Roles",
            "x-keywords": [
                "show roles",
                "all roles",
                "list roles",
                "db roles",
                "permissions roles",
            ],
        },
        title="List Database Roles",
    )


# ============================================================================
# Performance/Maintenance Configs
# ============================================================================


class PostgresExplainQueryConfig(BaseModel):
    """Explain a query's execution plan"""

    operation: Literal["explain_query_plan"] = Field(
        "explain_query_plan",
        json_schema_extra={
            "const": "explain_query_plan",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Explain Query Plan",
            "x-keywords": [
                "explain plan",
                "query plan",
                "execution plan",
                "analyze query",
                "explain analyze",
                "query cost",
            ],
        },
        title="Explain Query Plan",
    )
    query: str = Field(
        ...,
        title="SQL Query",
        description="Query to explain",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "SELECT * FROM users WHERE active = true",
        },
    )
    analyze: Optional[bool] = Field(
        False,
        title="Analyze",
        description="Execute the query and show actual execution times (EXPLAIN ANALYZE)",
    )
    verbose: Optional[bool] = Field(
        False, title="Verbose", description="Show additional information in the plan"
    )


class PostgresVacuumTableConfig(BaseModel):
    """Vacuum a table to reclaim storage and update statistics"""

    operation: Literal["vacuum_table"] = Field(
        "vacuum_table",
        json_schema_extra={
            "const": "vacuum_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Vacuum Table",
            "x-keywords": [
                "vacuum",
                "reclaim storage",
                "clean up table",
                "vacuum full",
            ],
        },
        title="Vacuum Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to vacuum"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )
    full: Optional[bool] = Field(
        False,
        title="Full",
        description="Perform a VACUUM FULL (more thorough, locks table)",
    )
    analyze: Optional[bool] = Field(
        True, title="Analyze", description="Update statistics for the query planner"
    )


class PostgresAnalyzeTableConfig(BaseModel):
    """Analyze a table to update statistics"""

    operation: Literal["analyze_table_statistics"] = Field(
        "analyze_table_statistics",
        json_schema_extra={
            "const": "analyze_table_statistics",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Analyze Table Statistics",
            "x-keywords": [
                "analyze table",
                "update statistics",
                "refresh stats",
                "gather statistics",
            ],
        },
        title="Analyze Table Statistics",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to analyze"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


# ============================================================================
# Transaction Management Configs
# ============================================================================


class PostgresBeginTransactionConfig(BaseModel):
    """Begin a new transaction"""

    operation: Literal["begin_transaction"] = Field(
        "begin_transaction",
        json_schema_extra={
            "const": "begin_transaction",
            "ui:hidden": True,
            "x-category": "Transaction",
            "x-is-trigger": False,
            "x-display-name": "Begin Transaction",
            "x-keywords": ["start transaction", "begin tx", "open transaction"],
        },
        title="Begin Transaction",
    )
    isolation_level: Optional[str] = Field(
        None,
        title="Isolation Level (Optional)",
        description="Transaction isolation level",
        json_schema_extra={
            "enum": [
                "read_uncommitted",
                "read_committed",
                "repeatable_read",
                "serializable",
            ]
        },
    )


class PostgresCommitTransactionConfig(BaseModel):
    """Commit the current transaction"""

    operation: Literal["commit_transaction"] = Field(
        "commit_transaction",
        json_schema_extra={
            "const": "commit_transaction",
            "ui:hidden": True,
            "x-category": "Transaction",
            "x-is-trigger": False,
            "x-display-name": "Commit Transaction",
            "x-keywords": [
                "commit",
                "save transaction",
                "commit tx",
                "finish transaction",
            ],
        },
        title="Commit Transaction",
    )


class PostgresRollbackTransactionConfig(BaseModel):
    """Rollback the current transaction"""

    operation: Literal["rollback_transaction"] = Field(
        "rollback_transaction",
        json_schema_extra={
            "const": "rollback_transaction",
            "ui:hidden": True,
            "x-category": "Transaction",
            "x-is-trigger": False,
            "x-display-name": "Rollback Transaction",
            "x-keywords": [
                "rollback",
                "undo transaction",
                "abort transaction",
                "cancel transaction",
            ],
        },
        title="Rollback Transaction",
    )


# ============================================================================
# COPY Operations Configs
# ============================================================================


class PostgresCopyToTableConfig(BaseModel):
    """Bulk import data to a table using COPY"""

    operation: Literal["copy_data_to_table"] = Field(
        "copy_data_to_table",
        json_schema_extra={
            "const": "copy_data_to_table",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Copy Data to Table",
            "x-keywords": [
                "bulk load",
                "copy into table",
                "import csv",
                "load data",
                "ingest rows",
            ],
        },
        title="Copy Data to Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to import data into"
    )
    columns: Optional[List[str]] = Field(
        None,
        title="Columns (Optional)",
        description="List of column names (defaults to all columns)",
    )
    data: List[List[Any]] = Field(
        ..., title="Data Rows", description="List of data rows to import (as 2D array)"
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


class PostgresCopyFromTableConfig(BaseModel):
    """Bulk export data from a table using COPY"""

    operation: Literal["copy_data_from_table"] = Field(
        "copy_data_from_table",
        json_schema_extra={
            "const": "copy_data_from_table",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Copy Data from Table",
            "x-keywords": [
                "dump table",
                "copy out",
                "export csv",
                "extract rows",
                "unload data",
            ],
        },
        title="Copy Data from Table",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to export data from"
    )
    columns: Optional[List[str]] = Field(
        None,
        title="Columns (Optional)",
        description="List of column names to export (defaults to all columns)",
    )
    where_clause: Optional[str] = Field(
        None,
        title="WHERE Clause (Optional)",
        description="Optional WHERE clause to filter rows (e.g., 'id > 100')",
    )
    limit: Optional[int] = Field(
        None,
        title="Row Limit (Optional)",
        description="Maximum number of rows to export",
    )
    schema_name: str = Field(
        "public",
        title="Schema",
        description="Schema containing the table (default: public)",
    )


# ============================================================================
# Advanced Query Configs
# ============================================================================


class PostgresQueryCursorConfig(BaseModel):
    """Execute query with cursor for large result sets"""

    operation: Literal["run_query_with_cursor"] = Field(
        "run_query_with_cursor",
        json_schema_extra={
            "const": "run_query_with_cursor",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Run Query with Cursor",
            "x-keywords": [
                "stream rows",
                "cursor query",
                "large result set",
                "paginate query",
                "server side cursor",
            ],
        },
        title="Run Query with Cursor",
    )
    query: str = Field(
        ...,
        title="SQL Query",
        description="SELECT query to execute with cursor",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "SELECT * FROM large_table",
        },
    )
    params: Optional[List[Any]] = Field(
        None,
        title="Query Parameters",
        description="Parameters to safely substitute into query ($1, $2, etc.)",
    )
    batch_size: Optional[int] = Field(
        1000,
        title="Batch Size",
        description="Number of rows to fetch per batch (default: 1000)",
        ge=1,
        le=10000,
    )
    max_rows: Optional[int] = Field(
        10000,
        title="Max Rows",
        description="Maximum total rows to return (default: 10000)",
        ge=1,
        le=100000,
    )


# ============================================================================
# Discriminated Union
# ============================================================================

PostgresConfig = Annotated[
    Union[
        # Query & Execute Operations (6)
        PostgresQueryConfig,
        PostgresExecuteConfig,
        PostgresExecuteManyConfig,
        PostgresQueryCursorConfig,
        PostgresCopyToTableConfig,
        PostgresCopyFromTableConfig,
        # Table Operations (6)
        PostgresListTablesConfig,
        PostgresListColumnsConfig,
        PostgresGetTableInfoConfig,
        PostgresCreateTableConfig,
        PostgresDropTableConfig,
        PostgresTruncateTableConfig,
        # Schema Operations (3)
        PostgresListSchemasConfig,
        PostgresCreateSchemaConfig,
        PostgresDropSchemaConfig,
        # Database Operations (1)
        PostgresListDatabasesConfig,
        # Index Operations (3)
        PostgresListIndexesConfig,
        PostgresCreateIndexConfig,
        PostgresDropIndexConfig,
        # View Operations (3)
        PostgresListViewsConfig,
        PostgresCreateViewConfig,
        PostgresDropViewConfig,
        # Sequence Operations (4)
        PostgresListSequencesConfig,
        PostgresGetNextSequenceValueConfig,
        PostgresGetCurrentSequenceValueConfig,
        PostgresSetSequenceValueConfig,
        # Function Operations (2)
        PostgresListFunctionsConfig,
        PostgresCallFunctionConfig,
        # Constraint Operations (1)
        PostgresListConstraintsConfig,
        # Trigger Operations (1)
        PostgresListTriggersConfig,
        # Extension Operations (2)
        PostgresListExtensionsConfig,
        PostgresCreateExtensionConfig,
        # User/Role Operations (2)
        PostgresListUsersConfig,
        PostgresListRolesConfig,
        # Performance/Maintenance Operations (3)
        PostgresExplainQueryConfig,
        PostgresVacuumTableConfig,
        PostgresAnalyzeTableConfig,
        # Transaction Operations (3)
        PostgresBeginTransactionConfig,
        PostgresCommitTransactionConfig,
        PostgresRollbackTransactionConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class PostgresNodeConfig(NodeConfig[PostgresConfig, PostgresCredential]):
    """Full configuration for PostgreSQL node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class PostgresNode(WorkflowNode):
    """
    PostgreSQL automation node.

    Executes PostgreSQL database operations for workflow automation.
    Uses asyncpg for high-performance async database access.
    """

    edit_examples = [
        "Query users table where status=active and select email,created_at",
        "Insert new order record with customer_id and timestamp",
        "Update user profile picture URL where user_id matches",
        "Delete archived records older than 1 year from archive table",
        "List all tables in schema and get column details for users table",
        "Execute bulk update to set last_login for active users",
        "Query sales data with GROUP BY and ORDER for monthly report",
    ]

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return PostgresNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured database operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, PostgresNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Database credentials are required. Add a connection string or individual credentials."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Query & Execute Operations
            "run_select_query": self._handle_query,
            "execute_sql_statement": self._handle_execute,
            "execute_batch_statements": self._handle_execute_many,
            "run_query_with_cursor": self._handle_query_cursor,
            "copy_data_to_table": self._handle_copy_to_table,
            "copy_data_from_table": self._handle_copy_from_table,
            # Table Operations
            "list_schema_tables": self._handle_list_tables,
            "list_table_columns": self._handle_list_columns,
            "get_table_info": self._handle_get_table_info,
            "create_table": self._handle_create_table,
            "drop_table": self._handle_drop_table,
            "truncate_table": self._handle_truncate_table,
            # Schema Operations
            "list_schemas": self._handle_list_schemas,
            "create_schema": self._handle_create_schema,
            "drop_schema": self._handle_drop_schema,
            # Database Operations
            "list_databases": self._handle_list_databases,
            # Index Operations
            "list_schema_indexes": self._handle_list_indexes,
            "create_index": self._handle_create_index,
            "drop_index": self._handle_drop_index,
            # View Operations
            "list_schema_views": self._handle_list_views,
            "create_view": self._handle_create_view,
            "drop_view": self._handle_drop_view,
            # Sequence Operations
            "list_schema_sequences": self._handle_list_sequences,
            "get_sequence_next_value": self._handle_get_next_sequence_value,
            "get_sequence_current_value": self._handle_get_current_sequence_value,
            "set_sequence_value": self._handle_set_sequence_value,
            # Function Operations
            "list_schema_functions": self._handle_list_functions,
            "call_database_function": self._handle_call_function,
            # Constraint Operations
            "list_table_constraints": self._handle_list_constraints,
            # Trigger Operations
            "list_schema_triggers": self._handle_list_triggers,
            # Extension Operations
            "list_extensions": self._handle_list_extensions,
            "install_extension": self._handle_create_extension,
            # User/Role Operations
            "list_database_users": self._handle_list_users,
            "list_database_roles": self._handle_list_roles,
            # Performance/Maintenance Operations
            "explain_query_plan": self._handle_explain_query,
            "vacuum_table": self._handle_vacuum_table,
            "analyze_table_statistics": self._handle_analyze_table,
            # Transaction Operations
            "begin_transaction": self._handle_begin_transaction,
            "commit_transaction": self._handle_commit_transaction,
            "rollback_transaction": self._handle_rollback_transaction,
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
    # Connection Helper
    # =========================================================================

    async def _get_connection(
        self, credentials: PostgresCredential
    ) -> asyncpg.Connection:
        """
        Establish a database connection from credentials.

        Args:
            credentials: Connection string or individual credentials

        Returns:
            asyncpg Connection object

        Note: statement_cache_size=0 disables prepared statement caching to avoid
        conflicts with connection pooling (pgbouncer) or reused connections.
        """
        if isinstance(credentials, PostgresConnectionStringCredential):
            parsed = _parse_safe_postgres_dsn(credentials.connection_string)
            return await _connect_pinned_postgres(
                parsed.pop("host"),
                parsed.pop("port"),
                **parsed,
            )
        elif isinstance(credentials, PostgresCredentialsCredential):
            return await _connect_pinned_postgres(
                credentials.host,
                credentials.port,
                database=credentials.database,
                user=credentials.user,
                password=credentials.password,
                ssl=_postgres_ssl_context(credentials.ssl_mode),
            )
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    # =========================================================================
    # Query Operation Handler
    # =========================================================================

    async def _handle_query(
        self, config: PostgresQueryConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Execute a SELECT query and return results."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            # Add LIMIT if not already present and limit is specified
            query = config.query.strip()
            # Remove trailing semicolons (they're optional in asyncpg and cause issues with LIMIT)
            query = query.rstrip(";").strip()
            if config.limit and "LIMIT" not in query.upper():
                query = f"{query} LIMIT {config.limit}"

            # Execute query with parameters
            params = config.params or []
            rows = await conn.fetch(query, *params)
            query_time = (time.time() - query_start) * 1000

            # Convert records to dicts
            result_rows = [dict(row) for row in rows]

            return {
                "status": "success",
                "action": "run_select_query",
                "data": {
                    "rows": result_rows,
                    "row_count": len(result_rows),
                    "columns": list(rows[0].keys()) if rows else [],
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] Query error: {e}")
            return {
                "status": "error",
                "action": "run_select_query",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "run_select_query",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Execute Operation Handler
    # =========================================================================

    async def _handle_execute(
        self, config: PostgresExecuteConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Execute an INSERT, UPDATE, DELETE, or other statement."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()
            params = config.params or []

            if config.return_rows:
                # For RETURNING clause, use fetch
                rows = await conn.fetch(config.statement, *params)
                result_rows = [dict(row) for row in rows]
                exec_time = (time.time() - exec_start) * 1000

                return {
                    "status": "success",
                    "action": "execute_sql_statement",
                    "data": {"rows": result_rows, "row_count": len(result_rows)},
                    "timing_ms": {
                        "connect": round(connect_time, 2),
                        "execute": round(exec_time, 2),
                    },
                }
            else:
                # For non-returning statements, use execute
                result = await conn.execute(config.statement, *params)
                exec_time = (time.time() - exec_start) * 1000

                # Parse result string (e.g., "INSERT 0 1", "UPDATE 5", "DELETE 3")
                affected_rows = 0
                if result:
                    parts = result.split()
                    if len(parts) >= 2 and parts[-1].isdigit():
                        affected_rows = int(parts[-1])

                return {
                    "status": "success",
                    "action": "execute_sql_statement",
                    "data": {"command": result, "affected_rows": affected_rows},
                    "timing_ms": {
                        "connect": round(connect_time, 2),
                        "execute": round(exec_time, 2),
                    },
                }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] Execute error: {e}")
            return {
                "status": "error",
                "action": "execute_sql_statement",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "execute_sql_statement",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Execute Many Operation Handler
    # =========================================================================

    async def _handle_execute_many(
        self, config: PostgresExecuteManyConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Execute a statement with multiple parameter sets (batch)."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            # Use executemany for batch operations
            await conn.executemany(config.statement, config.params_list)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "execute_batch_statements",
                "data": {"executed_count": len(config.params_list)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ExecuteMany error: {e}")
            return {
                "status": "error",
                "action": "execute_batch_statements",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "execute_batch_statements",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # List Tables Operation Handler
    # =========================================================================

    async def _handle_list_tables(
        self, config: PostgresListTablesConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all tables in a schema."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            # Build query based on whether to include views
            table_types = "'BASE TABLE'"
            if config.include_views:
                table_types = "'BASE TABLE', 'VIEW'"

            query = f"""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = $1
                AND table_type IN ({table_types})
                ORDER BY table_name
            """

            rows = await conn.fetch(query, config.schema_name)
            query_time = (time.time() - query_start) * 1000

            tables = [
                {"name": row["table_name"], "type": row["table_type"]} for row in rows
            ]

            return {
                "status": "success",
                "action": "list_schema_tables",
                "data": {
                    "schema": config.schema_name,
                    "tables": tables,
                    "count": len(tables),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListTables error: {e}")
            return {
                "status": "error",
                "action": "list_schema_tables",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_tables",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # List Columns Operation Handler
    # =========================================================================

    async def _handle_list_columns(
        self, config: PostgresListColumnsConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Get column metadata for a table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            query = """
                SELECT
                    column_name,
                    data_type,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
            """

            rows = await conn.fetch(query, config.schema_name, config.table_name)
            query_time = (time.time() - query_start) * 1000

            columns = [
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "max_length": row["character_maximum_length"],
                    "precision": row["numeric_precision"],
                    "scale": row["numeric_scale"],
                    "nullable": row["is_nullable"] == "YES",
                    "default": row["column_default"],
                    "position": row["ordinal_position"],
                }
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_table_columns",
                "data": {
                    "schema": config.schema_name,
                    "table": config.table_name,
                    "columns": columns,
                    "count": len(columns),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListColumns error: {e}")
            return {
                "status": "error",
                "action": "list_table_columns",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_table_columns",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Get Table Info Operation Handler
    # =========================================================================

    async def _handle_get_table_info(
        self, config: PostgresGetTableInfoConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Get detailed information about a table including constraints and indexes."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            # Get columns
            columns_query = """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
            """
            columns = await conn.fetch(
                columns_query, config.schema_name, config.table_name
            )

            # Get primary key
            pk_query = """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            """
            pk_columns = await conn.fetch(
                pk_query, config.schema_name, config.table_name
            )

            # Get foreign keys
            fk_query = """
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            """
            foreign_keys = await conn.fetch(
                fk_query, config.schema_name, config.table_name
            )

            # Get indexes
            idx_query = """
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = $1 AND tablename = $2
            """
            indexes = await conn.fetch(idx_query, config.schema_name, config.table_name)

            # Get row count estimate
            count_query = """
                SELECT reltuples::bigint AS estimate
                FROM pg_class
                WHERE oid = ($1 || '.' || $2)::regclass
            """
            try:
                count_result = await conn.fetchrow(
                    count_query, config.schema_name, config.table_name
                )
                row_count_estimate = count_result["estimate"] if count_result else None
            except Exception:
                row_count_estimate = None

            query_time = (time.time() - query_start) * 1000

            return {
                "status": "success",
                "action": "get_table_info",
                "data": {
                    "schema": config.schema_name,
                    "table": config.table_name,
                    "columns": [
                        {
                            "name": col["column_name"],
                            "type": col["data_type"],
                            "nullable": col["is_nullable"] == "YES",
                            "default": col["column_default"],
                        }
                        for col in columns
                    ],
                    "primary_key": [pk["column_name"] for pk in pk_columns],
                    "foreign_keys": [
                        {
                            "column": fk["column_name"],
                            "references_table": fk["foreign_table_name"],
                            "references_column": fk["foreign_column_name"],
                        }
                        for fk in foreign_keys
                    ],
                    "indexes": [
                        {"name": idx["indexname"], "definition": idx["indexdef"]}
                        for idx in indexes
                    ],
                    "row_count_estimate": row_count_estimate,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] GetTableInfo error: {e}")
            return {
                "status": "error",
                "action": "get_table_info",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "get_table_info",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Schema Management Handlers
    # =========================================================================

    async def _handle_list_schemas(
        self, config: PostgresListSchemasConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all schemas in the database."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schema_name
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            # Return simple list (frontend TableView handles primitives with "value" column)
            schemas = [row["schema_name"] for row in rows]

            return {
                "status": "success",
                "action": "list_schemas",
                "data": {"schemas": schemas, "count": len(schemas)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListSchemas error: {e}")
            return {
                "status": "error",
                "action": "list_schemas",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schemas",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_create_schema(
        self, config: PostgresCreateSchemaConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Create a new schema."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_not_exists = "IF NOT EXISTS " if config.if_not_exists else ""
            statement = f"CREATE SCHEMA {if_not_exists}{config.schema_name}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "create_schema",
                "data": {"schema_name": config.schema_name, "created": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CreateSchema error: {e}")
            return {
                "status": "error",
                "action": "create_schema",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "create_schema",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_drop_schema(
        self, config: PostgresDropSchemaConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Drop a schema."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_exists = "IF EXISTS " if config.if_exists else ""
            cascade = " CASCADE" if config.cascade else ""
            statement = f"DROP SCHEMA {if_exists}{config.schema_name}{cascade}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "drop_schema",
                "data": {"schema_name": config.schema_name, "dropped": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] DropSchema error: {e}")
            return {
                "status": "error",
                "action": "drop_schema",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "drop_schema",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Database Management Handlers
    # =========================================================================

    async def _handle_list_databases(
        self, config: PostgresListDatabasesConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all databases."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT datname, pg_catalog.pg_get_userbyid(datdba) as owner, 
                       pg_catalog.pg_size_pretty(pg_catalog.pg_database_size(datname)) as size
                FROM pg_catalog.pg_database
                WHERE datistemplate = false
                ORDER BY datname
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            databases = [
                {"name": row["datname"], "owner": row["owner"], "size": row["size"]}
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_databases",
                "data": {"databases": databases, "count": len(databases)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListDatabases error: {e}")
            return {
                "status": "error",
                "action": "list_databases",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_databases",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Index Management Handlers
    # =========================================================================

    async def _handle_list_indexes(
        self, config: PostgresListIndexesConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all indexes."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            where_clause = f"WHERE schemaname = '{config.schema_name}'"
            if config.table_name:
                where_clause += f" AND tablename = '{config.table_name}'"

            query = f"""
                SELECT indexname, tablename, indexdef
                FROM pg_indexes
                {where_clause}
                ORDER BY indexname
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            indexes = [
                {
                    "name": row["indexname"],
                    "table": row["tablename"],
                    "definition": row["indexdef"],
                }
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_schema_indexes",
                "data": {
                    "schema": config.schema_name,
                    "table": config.table_name,
                    "indexes": indexes,
                    "count": len(indexes),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListIndexes error: {e}")
            return {
                "status": "error",
                "action": "list_schema_indexes",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_indexes",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_create_index(
        self, config: PostgresCreateIndexConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Create an index."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            unique = "UNIQUE " if config.unique else ""
            if_not_exists = "IF NOT EXISTS " if config.if_not_exists else ""
            columns = ", ".join(config.columns)
            full_table_name = f"{config.schema_name}.{config.table_name}"

            statement = f"CREATE {unique}INDEX {if_not_exists}{config.index_name} ON {full_table_name} ({columns})"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "create_index",
                "data": {
                    "index_name": config.index_name,
                    "table": config.table_name,
                    "columns": config.columns,
                    "unique": config.unique,
                    "created": True,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CreateIndex error: {e}")
            return {
                "status": "error",
                "action": "create_index",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "create_index",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_drop_index(
        self, config: PostgresDropIndexConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Drop an index."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_exists = "IF EXISTS " if config.if_exists else ""
            full_index_name = f"{config.schema_name}.{config.index_name}"
            statement = f"DROP INDEX {if_exists}{full_index_name}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "drop_index",
                "data": {"index_name": config.index_name, "dropped": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] DropIndex error: {e}")
            return {
                "status": "error",
                "action": "drop_index",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "drop_index",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # View Management Handlers
    # =========================================================================

    async def _handle_list_views(
        self, config: PostgresListViewsConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all views."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT table_name, view_definition
                FROM information_schema.views
                WHERE table_schema = $1
                ORDER BY table_name
            """
            rows = await conn.fetch(query, config.schema_name)
            query_time = (time.time() - query_start) * 1000

            views = [
                {"name": row["table_name"], "definition": row["view_definition"]}
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_schema_views",
                "data": {
                    "schema": config.schema_name,
                    "views": views,
                    "count": len(views),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListViews error: {e}")
            return {
                "status": "error",
                "action": "list_schema_views",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_views",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_create_view(
        self, config: PostgresCreateViewConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Create a view."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            or_replace = "OR REPLACE " if config.or_replace else ""
            full_view_name = f"{config.schema_name}.{config.view_name}"
            statement = f"CREATE {or_replace}VIEW {full_view_name} AS {config.query}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "create_view",
                "data": {
                    "view_name": config.view_name,
                    "schema": config.schema_name,
                    "created": True,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CreateView error: {e}")
            return {
                "status": "error",
                "action": "create_view",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "create_view",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_drop_view(
        self, config: PostgresDropViewConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Drop a view."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_exists = "IF EXISTS " if config.if_exists else ""
            full_view_name = f"{config.schema_name}.{config.view_name}"
            statement = f"DROP VIEW {if_exists}{full_view_name}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "drop_view",
                "data": {"view_name": config.view_name, "dropped": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] DropView error: {e}")
            return {
                "status": "error",
                "action": "drop_view",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "drop_view",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Sequence Management Handlers
    # =========================================================================

    async def _handle_list_sequences(
        self, config: PostgresListSequencesConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all sequences."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT sequence_name
                FROM information_schema.sequences
                WHERE sequence_schema = $1
                ORDER BY sequence_name
            """
            rows = await conn.fetch(query, config.schema_name)
            query_time = (time.time() - query_start) * 1000

            # Return simple list (frontend TableView handles primitives with "value" column)
            sequences = [row["sequence_name"] for row in rows]

            return {
                "status": "success",
                "action": "list_schema_sequences",
                "data": {
                    "schema": config.schema_name,
                    "sequences": sequences,
                    "count": len(sequences),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListSequences error: {e}")
            return {
                "status": "error",
                "action": "list_schema_sequences",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_sequences",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_get_next_sequence_value(
        self,
        config: PostgresGetNextSequenceValueConfig,
        credentials: PostgresCredential,
    ) -> Dict[str, Any]:
        """Get next value from sequence (nextval)."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            full_sequence_name = f"{config.schema_name}.{config.sequence_name}"
            value = await conn.fetchval(f"SELECT nextval('{full_sequence_name}')")
            query_time = (time.time() - query_start) * 1000

            return {
                "status": "success",
                "action": "get_sequence_next_value",
                "data": {"sequence_name": config.sequence_name, "value": value},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] GetNextSequenceValue error: {e}")
            return {
                "status": "error",
                "action": "get_sequence_next_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "get_sequence_next_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_get_current_sequence_value(
        self,
        config: PostgresGetCurrentSequenceValueConfig,
        credentials: PostgresCredential,
    ) -> Dict[str, Any]:
        """Get current value from sequence (currval)."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            full_sequence_name = f"{config.schema_name}.{config.sequence_name}"
            value = await conn.fetchval(f"SELECT currval('{full_sequence_name}')")
            query_time = (time.time() - query_start) * 1000

            return {
                "status": "success",
                "action": "get_sequence_current_value",
                "data": {"sequence_name": config.sequence_name, "value": value},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] GetCurrentSequenceValue error: {e}")
            return {
                "status": "error",
                "action": "get_sequence_current_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "get_sequence_current_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_set_sequence_value(
        self, config: PostgresSetSequenceValueConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Set sequence value (setval)."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()
            full_sequence_name = f"{config.schema_name}.{config.sequence_name}"
            is_called_str = "true" if config.is_called else "false"
            await conn.execute(
                f"SELECT setval('{full_sequence_name}', {config.value}, {is_called_str})"
            )
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "set_sequence_value",
                "data": {
                    "sequence_name": config.sequence_name,
                    "value": config.value,
                    "is_called": config.is_called,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] SetSequenceValue error: {e}")
            return {
                "status": "error",
                "action": "set_sequence_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "set_sequence_value",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Function/Procedure Handlers
    # =========================================================================

    async def _handle_list_functions(
        self, config: PostgresListFunctionsConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all functions."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT routine_name, routine_type
                FROM information_schema.routines
                WHERE routine_schema = $1
                ORDER BY routine_name
            """
            rows = await conn.fetch(query, config.schema_name)
            query_time = (time.time() - query_start) * 1000

            functions = [
                {"name": row["routine_name"], "type": row["routine_type"]}
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_schema_functions",
                "data": {
                    "schema": config.schema_name,
                    "functions": functions,
                    "count": len(functions),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListFunctions error: {e}")
            return {
                "status": "error",
                "action": "list_schema_functions",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_functions",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_call_function(
        self, config: PostgresCallFunctionConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Call a PostgreSQL function."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            full_function_name = f"{config.schema_name}.{config.function_name}"
            params = config.params or []

            # Build parameter placeholders
            param_placeholders = ", ".join([f"${i+1}" for i in range(len(params))])
            query = f"SELECT * FROM {full_function_name}({param_placeholders})"

            rows = await conn.fetch(query, *params)
            exec_time = (time.time() - exec_start) * 1000

            result_rows = [dict(row) for row in rows]

            return {
                "status": "success",
                "action": "call_database_function",
                "data": {
                    "function_name": config.function_name,
                    "result": result_rows,
                    "row_count": len(result_rows),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CallFunction error: {e}")
            return {
                "status": "error",
                "action": "call_database_function",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "call_database_function",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Constraint Management Handlers
    # =========================================================================

    async def _handle_list_constraints(
        self, config: PostgresListConstraintsConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all constraints for a table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT constraint_name, constraint_type
                FROM information_schema.table_constraints
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY constraint_name
            """
            rows = await conn.fetch(query, config.schema_name, config.table_name)
            query_time = (time.time() - query_start) * 1000

            constraints = [
                {"name": row["constraint_name"], "type": row["constraint_type"]}
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_table_constraints",
                "data": {
                    "schema": config.schema_name,
                    "table": config.table_name,
                    "constraints": constraints,
                    "count": len(constraints),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListConstraints error: {e}")
            return {
                "status": "error",
                "action": "list_table_constraints",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_table_constraints",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Trigger Management Handlers
    # =========================================================================

    async def _handle_list_triggers(
        self, config: PostgresListTriggersConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all triggers."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            where_clause = f"WHERE trigger_schema = '{config.schema_name}'"
            if config.table_name:
                where_clause += f" AND event_object_table = '{config.table_name}'"

            query = f"""
                SELECT trigger_name, event_object_table, action_statement
                FROM information_schema.triggers
                {where_clause}
                ORDER BY trigger_name
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            triggers = [
                {
                    "name": row["trigger_name"],
                    "table": row["event_object_table"],
                    "action": row["action_statement"],
                }
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_schema_triggers",
                "data": {
                    "schema": config.schema_name,
                    "table": config.table_name,
                    "triggers": triggers,
                    "count": len(triggers),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListTriggers error: {e}")
            return {
                "status": "error",
                "action": "list_schema_triggers",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_schema_triggers",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Extension Management Handlers
    # =========================================================================

    async def _handle_list_extensions(
        self, config: PostgresListExtensionsConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all installed extensions."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT extname, extversion, extrelocatable
                FROM pg_extension
                ORDER BY extname
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            extensions = [
                {
                    "name": row["extname"],
                    "version": row["extversion"],
                    "relocatable": row["extrelocatable"],
                }
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_extensions",
                "data": {"extensions": extensions, "count": len(extensions)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListExtensions error: {e}")
            return {
                "status": "error",
                "action": "list_extensions",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_extensions",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_create_extension(
        self, config: PostgresCreateExtensionConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Create/install an extension."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_not_exists = "IF NOT EXISTS " if config.if_not_exists else ""
            schema_clause = (
                f" SCHEMA {config.schema_name}" if config.schema_name else ""
            )
            statement = f"CREATE EXTENSION {if_not_exists}{config.extension_name}{schema_clause}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "install_extension",
                "data": {
                    "extension_name": config.extension_name,
                    "schema": config.schema_name,
                    "created": True,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CreateExtension error: {e}")
            return {
                "status": "error",
                "action": "install_extension",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "install_extension",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Table Management Handlers
    # =========================================================================

    async def _handle_create_table(
        self, config: PostgresCreateTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Create a new table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_not_exists = "IF NOT EXISTS " if config.if_not_exists else ""
            full_table_name = f"{config.schema_name}.{config.table_name}"
            statement = (
                f"CREATE TABLE {if_not_exists}{full_table_name} ({config.columns})"
            )

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "create_table",
                "data": {
                    "table_name": config.table_name,
                    "schema": config.schema_name,
                    "created": True,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CreateTable error: {e}")
            return {
                "status": "error",
                "action": "create_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "create_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_drop_table(
        self, config: PostgresDropTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Drop a table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            if_exists = "IF EXISTS " if config.if_exists else ""
            cascade = " CASCADE" if config.cascade else ""
            full_table_name = f"{config.schema_name}.{config.table_name}"
            statement = f"DROP TABLE {if_exists}{full_table_name}{cascade}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "drop_table",
                "data": {"table_name": config.table_name, "dropped": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] DropTable error: {e}")
            return {
                "status": "error",
                "action": "drop_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "drop_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_truncate_table(
        self, config: PostgresTruncateTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Truncate a table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            full_table_name = f"{config.schema_name}.{config.table_name}"
            restart = " RESTART IDENTITY" if config.restart_identity else ""
            cascade = " CASCADE" if config.cascade else ""
            statement = f"TRUNCATE TABLE {full_table_name}{restart}{cascade}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "truncate_table",
                "data": {"table_name": config.table_name, "truncated": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] TruncateTable error: {e}")
            return {
                "status": "error",
                "action": "truncate_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "truncate_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # User/Role Management Handlers
    # =========================================================================

    async def _handle_list_users(
        self, config: PostgresListUsersConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all database users."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT
                    rolname as username,
                    rolsuper as is_superuser,
                    rolcreatedb as can_create_db,
                    rolcreaterole as can_create_role
                FROM pg_catalog.pg_roles
                WHERE rolcanlogin = TRUE
                ORDER BY rolname
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            users = [dict(row) for row in rows]

            return {
                "status": "success",
                "action": "list_database_users",
                "data": {"users": users, "count": len(users)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListUsers error: {e}")
            return {
                "status": "error",
                "action": "list_database_users",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_database_users",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_list_roles(
        self, config: PostgresListRolesConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """List all database roles."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()
            query = """
                SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
                FROM pg_catalog.pg_roles
                ORDER BY rolname
            """
            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            roles = [
                {
                    "rolename": row["rolname"],
                    "is_superuser": row["rolsuper"],
                    "can_create_db": row["rolcreatedb"],
                    "can_create_role": row["rolcreaterole"],
                }
                for row in rows
            ]

            return {
                "status": "success",
                "action": "list_database_roles",
                "data": {"roles": roles, "count": len(roles)},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ListRoles error: {e}")
            return {
                "status": "error",
                "action": "list_database_roles",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "list_database_roles",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Performance/Maintenance Handlers
    # =========================================================================

    async def _handle_explain_query(
        self, config: PostgresExplainQueryConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Explain a query's execution plan."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            options = []
            if config.analyze:
                options.append("ANALYZE")
            if config.verbose:
                options.append("VERBOSE")

            options_str = ", ".join(options)
            explain_cmd = (
                f"EXPLAIN ({options_str}) {config.query}"
                if options
                else f"EXPLAIN {config.query}"
            )

            rows = await conn.fetch(explain_cmd)
            query_time = (time.time() - query_start) * 1000

            # Return simple list (frontend TableView handles primitives with "value" column)
            plan = [row[0] for row in rows]

            return {
                "status": "success",
                "action": "explain_query_plan",
                "data": {
                    "plan": plan,
                    "analyzed": config.analyze,
                    "verbose": config.verbose,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] ExplainQuery error: {e}")
            return {
                "status": "error",
                "action": "explain_query_plan",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "explain_query_plan",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_vacuum_table(
        self, config: PostgresVacuumTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Vacuum a table."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            full_table_name = f"{config.schema_name}.{config.table_name}"
            vacuum_type = "VACUUM FULL" if config.full else "VACUUM"
            analyze = " ANALYZE" if config.analyze else ""
            statement = f"{vacuum_type}{analyze} {full_table_name}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "vacuum_table",
                "data": {
                    "table_name": config.table_name,
                    "full": config.full,
                    "analyze": config.analyze,
                    "vacuumed": True,
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] VacuumTable error: {e}")
            return {
                "status": "error",
                "action": "vacuum_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "vacuum_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_analyze_table(
        self, config: PostgresAnalyzeTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Analyze a table to update statistics."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            full_table_name = f"{config.schema_name}.{config.table_name}"
            statement = f"ANALYZE {full_table_name}"

            await conn.execute(statement)
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "analyze_table_statistics",
                "data": {"table_name": config.table_name, "analyzed": True},
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] AnalyzeTable error: {e}")
            return {
                "status": "error",
                "action": "analyze_table_statistics",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "analyze_table_statistics",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Transaction Management Handlers
    # =========================================================================

    async def _handle_begin_transaction(
        self, config: PostgresBeginTransactionConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Begin a transaction."""
        return {
            "status": "error",
            "action": "begin_transaction",
            "error": "Transaction management operations not supported in stateless workflow context. Use transaction() context manager in custom code instead.",
            "error_type": "UnsupportedOperation",
        }

    async def _handle_commit_transaction(
        self, config: PostgresCommitTransactionConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Commit a transaction."""
        return {
            "status": "error",
            "action": "commit_transaction",
            "error": "Transaction management operations not supported in stateless workflow context. Use transaction() context manager in custom code instead.",
            "error_type": "UnsupportedOperation",
        }

    async def _handle_rollback_transaction(
        self, config: PostgresRollbackTransactionConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Rollback a transaction."""
        return {
            "status": "error",
            "action": "rollback_transaction",
            "error": "Transaction management operations not supported in stateless workflow context. Use transaction() context manager in custom code instead.",
            "error_type": "UnsupportedOperation",
        }

    # =========================================================================
    # COPY Operations Handlers
    # =========================================================================

    async def _handle_copy_to_table(
        self, config: PostgresCopyToTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Bulk import data using COPY."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            exec_start = time.time()

            full_table_name = f"{config.schema_name}.{config.table_name}"
            columns = config.columns or None

            # Convert data to list of tuples
            records = [tuple(row) for row in config.data]

            result = await conn.copy_records_to_table(
                full_table_name, records=records, columns=columns
            )
            exec_time = (time.time() - exec_start) * 1000

            return {
                "status": "success",
                "action": "copy_data_to_table",
                "data": {
                    "table_name": config.table_name,
                    "rows_imported": len(records),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "execute": round(exec_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CopyToTable error: {e}")
            return {
                "status": "error",
                "action": "copy_data_to_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "copy_data_to_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    async def _handle_copy_from_table(
        self, config: PostgresCopyFromTableConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Bulk export data using COPY."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            full_table_name = f"{config.schema_name}.{config.table_name}"
            columns_str = ", ".join(config.columns) if config.columns else "*"

            # Build query
            query = f"SELECT {columns_str} FROM {full_table_name}"
            if config.where_clause:
                query += f" WHERE {config.where_clause}"
            if config.limit:
                query += f" LIMIT {config.limit}"

            rows = await conn.fetch(query)
            query_time = (time.time() - query_start) * 1000

            # Convert to list of dicts for consistent frontend display
            result_data = [dict(row) for row in rows]

            return {
                "status": "success",
                "action": "copy_data_from_table",
                "data": {
                    "table_name": config.table_name,
                    "rows": result_data,
                    "row_count": len(result_data),
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] CopyFromTable error: {e}")
            return {
                "status": "error",
                "action": "copy_data_from_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "copy_data_from_table",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()

    # =========================================================================
    # Advanced Query Handlers
    # =========================================================================

    async def _handle_query_cursor(
        self, config: PostgresQueryCursorConfig, credentials: PostgresCredential
    ) -> Dict[str, Any]:
        """Execute query with cursor for large result sets."""
        conn = None
        try:
            connect_start = time.time()
            conn = await self._get_connection(credentials)
            connect_time = (time.time() - connect_start) * 1000

            query_start = time.time()

            params = config.params or []
            all_rows = []
            total_fetched = 0

            # Use cursor to fetch data in batches
            async with conn.transaction():
                cursor = await conn.cursor(config.query, *params)

                while total_fetched < config.max_rows:
                    batch = await cursor.fetch(config.batch_size)
                    if not batch:
                        break

                    all_rows.extend([dict(row) for row in batch])
                    total_fetched += len(batch)

                    # Stop if we've reached max_rows
                    if total_fetched >= config.max_rows:
                        all_rows = all_rows[: config.max_rows]
                        break

            query_time = (time.time() - query_start) * 1000

            return {
                "status": "success",
                "action": "run_query_with_cursor",
                "data": {
                    "rows": all_rows,
                    "row_count": len(all_rows),
                    "batch_size": config.batch_size,
                    "max_rows_reached": len(all_rows) >= config.max_rows,
                    "columns": list(all_rows[0].keys()) if all_rows else [],
                },
                "timing_ms": {
                    "connect": round(connect_time, 2),
                    "query": round(query_time, 2),
                },
            }

        except asyncpg.PostgresError as e:
            logger.error(f"[PostgresNode] QueryCursor error: {e}")
            return {
                "status": "error",
                "action": "run_query_with_cursor",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        except Exception as e:
            logger.exception(f"[PostgresNode] Unexpected error: {e}")
            return {
                "status": "error",
                "action": "run_query_with_cursor",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            if conn:
                await conn.close()
