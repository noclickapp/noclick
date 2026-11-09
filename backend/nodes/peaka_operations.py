"""Peaka Gateway API 1.0 project data operations.

Contract: https://raw.githubusercontent.com/peakacom/docs/main/api-reference/peaka-openapi.json
Project and partner API keys use the same Bearer authentication for these routes.
"""
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PeakaOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"catalog_id", "schema_name", "table_name", "query_id", "connection_id"}:
            if not value.strip() or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a nonempty resource name or ID")
        return value


class PeakaListCatalogsConfig(PeakaOperation):
    """List catalogs in the connected project."""
    operation: Literal["list_catalogs"] = Field("list_catalogs", json_schema_extra={"ui:hidden": True})


class PeakaCreateCatalogConfig(PeakaOperation):
    """Create catalog in the connected project."""
    operation: Literal["create_catalog"] = Field("create_catalog", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100000)
    connection_id: str = Field(..., min_length=1, max_length=100000)
    extra_parameters: dict[str, Any] | None = None


class PeakaGetCatalogConfig(PeakaOperation):
    """Get catalog in the connected project."""
    operation: Literal["get_catalog"] = Field("get_catalog", json_schema_extra={"ui:hidden": True})
    catalog_id: str = Field(..., min_length=1, max_length=512)


class PeakaDeleteCatalogConfig(PeakaOperation):
    """Delete catalog in the connected project."""
    operation: Literal["delete_catalog"] = Field("delete_catalog", json_schema_extra={"ui:hidden": True})
    catalog_id: str = Field(..., min_length=1, max_length=512)


class PeakaListSchemasConfig(PeakaOperation):
    """List schemas in the connected project."""
    operation: Literal["list_schemas"] = Field("list_schemas", json_schema_extra={"ui:hidden": True})
    catalog_id: str = Field(..., min_length=1, max_length=512)


class PeakaListTablesConfig(PeakaOperation):
    """List tables in the connected project."""
    operation: Literal["list_tables"] = Field("list_tables", json_schema_extra={"ui:hidden": True})
    catalog_id: str = Field(..., min_length=1, max_length=512)
    schema_name: str = Field(..., min_length=1, max_length=512)


class PeakaListColumnsConfig(PeakaOperation):
    """List columns in the connected project."""
    operation: Literal["list_columns"] = Field("list_columns", json_schema_extra={"ui:hidden": True})
    catalog_id: str = Field(..., min_length=1, max_length=512)
    schema_name: str = Field(..., min_length=1, max_length=512)
    table_name: str = Field(..., min_length=1, max_length=512)


class PeakaListInternalTablesConfig(PeakaOperation):
    """List internal tables in the connected project."""
    operation: Literal["list_internal_tables"] = Field("list_internal_tables", json_schema_extra={"ui:hidden": True})


class PeakaCreateInternalTableConfig(PeakaOperation):
    """Create internal table in the connected project."""
    operation: Literal["create_internal_table"] = Field("create_internal_table", json_schema_extra={"ui:hidden": True})
    table_name: str = Field(..., min_length=1, max_length=512)


class PeakaDeleteInternalTableConfig(PeakaOperation):
    """Delete internal table in the connected project."""
    operation: Literal["delete_internal_table"] = Field("delete_internal_table", json_schema_extra={"ui:hidden": True})
    table_name: str = Field(..., min_length=1, max_length=512)


class PeakaListInternalColumnsConfig(PeakaOperation):
    """List internal columns in the connected project."""
    operation: Literal["list_internal_columns"] = Field("list_internal_columns", json_schema_extra={"ui:hidden": True})
    table_name: str = Field(..., min_length=1, max_length=512)


class PeakaListQueriesConfig(PeakaOperation):
    """List queries in the connected project."""
    operation: Literal["list_queries"] = Field("list_queries", json_schema_extra={"ui:hidden": True})


class PeakaCreateQueryConfig(PeakaOperation):
    """Create query in the connected project."""
    operation: Literal["create_query"] = Field("create_query", json_schema_extra={"ui:hidden": True})
    display_name: str = Field(..., min_length=1, max_length=100000)
    input_query: str = Field(..., min_length=1, max_length=100000)
    path: str | None = Field(None, max_length=2048)
    check_schema_exists: bool = True


class PeakaGetQueryConfig(PeakaOperation):
    """Get query in the connected project."""
    operation: Literal["get_query"] = Field("get_query", json_schema_extra={"ui:hidden": True})
    query_id: str = Field(..., min_length=1, max_length=512)


class PeakaUpdateQueryConfig(PeakaOperation):
    """Update query in the connected project."""
    operation: Literal["update_query"] = Field("update_query", json_schema_extra={"ui:hidden": True})
    query_id: str = Field(..., min_length=1, max_length=512)
    display_name: str = Field(..., min_length=1, max_length=100000)
    input_query: str = Field(..., min_length=1, max_length=100000)
    path: str | None = Field(None, max_length=2048)
    check_schema_exists: bool = True


class PeakaDeleteQueryConfig(PeakaOperation):
    """Delete query in the connected project."""
    operation: Literal["delete_query"] = Field("delete_query", json_schema_extra={"ui:hidden": True})
    query_id: str = Field(..., min_length=1, max_length=512)


class PeakaExecuteQueryConfig(PeakaOperation):
    """Execute query in the connected project."""
    operation: Literal["execute_query"] = Field("execute_query", json_schema_extra={"ui:hidden": True})
    statement: str = Field(..., min_length=1, max_length=100000)
    bindings: list[str] | None = None
    timeout: int | None = Field(None, ge=1, le=300)
    format: Literal["CELL_TYPED", "SIMPLE", "COMPACT"] = "SIMPLE"


PeakaConfig = Annotated[Union[
    PeakaListCatalogsConfig,
    PeakaCreateCatalogConfig,
    PeakaGetCatalogConfig,
    PeakaDeleteCatalogConfig,
    PeakaListSchemasConfig,
    PeakaListTablesConfig,
    PeakaListColumnsConfig,
    PeakaListInternalTablesConfig,
    PeakaCreateInternalTableConfig,
    PeakaDeleteInternalTableConfig,
    PeakaListInternalColumnsConfig,
    PeakaListQueriesConfig,
    PeakaCreateQueryConfig,
    PeakaGetQueryConfig,
    PeakaUpdateQueryConfig,
    PeakaDeleteQueryConfig,
    PeakaExecuteQueryConfig,
], Field(discriminator="operation")]

ROUTES = {'list_catalogs': ('GET', '/data/projects/{projectId}/catalogs'),
 'create_catalog': ('POST', '/data/projects/{projectId}/catalogs'),
 'get_catalog': ('GET', '/data/projects/{projectId}/catalogs/{catalogId}'),
 'delete_catalog': ('DELETE', '/data/projects/{projectId}/catalogs/{catalogId}'),
 'list_schemas': ('GET', '/data/projects/{projectId}/catalogs/{catalogId}/schemas'),
 'list_tables': ('GET', '/data/projects/{projectId}/catalogs/{catalogId}/schemas/{schemaName}/tables'),
 'list_columns': ('GET',
                  '/data/projects/{projectId}/catalogs/{catalogId}/schemas/{schemaName}/tables/{tableName}/columns'),
 'list_internal_tables': ('GET', '/data/projects/{projectId}/table'),
 'create_internal_table': ('POST', '/data/projects/{projectId}/table/{tableName}'),
 'delete_internal_table': ('DELETE', '/data/projects/{projectId}/table/{tableName}'),
 'list_internal_columns': ('GET', '/data/projects/{projectId}/table/{tableName}/columns'),
 'list_queries': ('GET', '/data/projects/{projectId}/queries'),
 'create_query': ('POST', '/data/projects/{projectId}/queries'),
 'get_query': ('GET', '/data/projects/{projectId}/queries/{queryId}'),
 'update_query': ('PUT', '/data/projects/{projectId}/queries/{queryId}'),
 'delete_query': ('DELETE', '/data/projects/{projectId}/queries/{queryId}'),
 'execute_query': ('POST', '/data/projects/{projectId}/queries/execute')}
PATH_FIELDS = {'catalogId': 'catalog_id', 'schemaName': 'schema_name', 'tableName': 'table_name', 'queryId': 'query_id'}
