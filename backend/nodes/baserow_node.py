"""Baserow database-token workflow actions.

Official API: https://api.baserow.io/api/redoc/
Database tokens cover table discovery, field discovery and row operations. Schema
mutation and webhook administration require a short-lived user JWT instead.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Json
from typing_extensions import TypedDict

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class BaserowDatabaseTokenCredential(BaseModel):
    credential_type: Literal["baserow_database_token"] = Field(
        "baserow_database_token", json_schema_extra={"ui:hidden": True}
    )
    database_token: str = Field(
        ...,
        title="Database Token",
        description="A database token with access to the tables and actions you need.",
        json_schema_extra={"ui:widget": "password"},
    )
    base_url: str = Field(
        "https://api.baserow.io",
        title="Baserow URL",
        description="Cloud API URL or the public HTTPS URL of your self-hosted Baserow instance.",
    )

    model_config = ConfigDict(
        title="Baserow Database Token",
        json_schema_extra={
            "x-credential-url": "https://baserow.io/user-docs/personal-api-tokens"
        }
    )


# Baserow's own MCP server: agents get its tools through a person's Baserow sign-in.
BaserowMcpCredential = mcp_credential("baserow", "https://api.baserow.io/mcp", app="Baserow")
BaserowCredential = Union[BaserowDatabaseTokenCredential, BaserowMcpCredential]


def _op(value: str, category: str, title: str, keywords: List[str]) -> Any:
    return Field(
        value,
        title=title,
        json_schema_extra={
            "const": value,
            "ui:hidden": True,
            "x-category": category,
            "x-is-trigger": False,
            "x-display-name": title,
            "x-keywords": keywords,
        },
    )


TABLE_FIELD = Field(
    ...,
    title="Table",
    description="Baserow table ID. Select an accessible table or enter its ID.",
    json_schema_extra={
        "x-dynamic-options": {
            "field_name": "table_id",
            "placeholder": "Select a table...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or enter a table ID",
        }
    },
)


class BaserowListTablesConfig(BaseModel):
    operation: Literal["list_tables"] = _op(
        "list_tables",
        "Tables",
        "List Accessible Tables",
        ["tables", "databases", "discover"],
    )


class BaserowListFieldsConfig(BaseModel):
    operation: Literal["list_fields"] = _op(
        "list_fields", "Tables", "List Table Fields", ["fields", "columns", "schema"]
    )
    table_id: int = TABLE_FIELD


class BaserowListRowsConfig(BaseModel):
    operation: Literal["list_rows"] = _op(
        "list_rows", "Rows", "List Rows", ["search", "filter", "query", "paginate"]
    )
    table_id: int = TABLE_FIELD
    page: int = Field(1, ge=1, title="Page")
    size: int = Field(100, ge=1, le=200, title="Page Size")
    search: Optional[str] = Field(None, title="Search")
    order_by: Optional[str] = Field(
        None,
        title="Order By",
        description="Comma-separated field names; prefix - for descending.",
    )
    filters: Optional[Union[Dict[str, Any], Json[Dict[str, Any]]]] = Field(
        None,
        title="Filters",
        description="Baserow advanced filter object with filter_type, filters and groups.",
    )
    view_id: Optional[int] = Field(
        None, title="View ID", description="Optionally limit rows to a view."
    )
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowGetRowConfig(BaseModel):
    operation: Literal["get_row"] = _op(
        "get_row", "Rows", "Get Row", ["read", "record"]
    )
    table_id: int = TABLE_FIELD
    row_id: int = Field(..., ge=1, title="Row ID")
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowCreateRowConfig(BaseModel):
    operation: Literal["create_row"] = _op(
        "create_row", "Rows", "Create Row", ["add", "insert", "record"]
    )
    table_id: int = TABLE_FIELD
    fields: Union[Dict[str, Any], Json[Dict[str, Any]]] = Field(
        ...,
        title="Field Values",
        description='Object keyed by the table\'s field names. Example: {"Name": "Ada"}.',
    )
    before_row_id: Optional[int] = Field(None, ge=1, title="Insert Before Row ID")
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowUpdateRowConfig(BaseModel):
    operation: Literal["update_row"] = _op(
        "update_row", "Rows", "Update Row", ["edit", "patch", "record"]
    )
    table_id: int = TABLE_FIELD
    row_id: int = Field(..., ge=1, title="Row ID")
    fields: Union[Dict[str, Any], Json[Dict[str, Any]]] = Field(
        ...,
        title="Field Values",
        description="Object of fields to change, keyed by field name.",
    )
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowMoveRowConfig(BaseModel):
    operation: Literal["move_row"] = _op(
        "move_row", "Rows", "Move Row", ["reorder", "position"]
    )
    table_id: int = TABLE_FIELD
    row_id: int = Field(..., ge=1, title="Row ID")
    before_row_id: Optional[int] = Field(
        None, ge=1, title="Before Row ID", description="Leave blank to move to the end."
    )
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowDeleteRowConfig(BaseModel):
    operation: Literal["delete_row"] = _op(
        "delete_row", "Rows", "Delete Row", ["remove", "record"]
    )
    table_id: int = TABLE_FIELD
    row_id: int = Field(..., ge=1, title="Row ID")


class BaserowBatchCreateRowsConfig(BaseModel):
    operation: Literal["batch_create_rows"] = _op(
        "batch_create_rows",
        "Batch",
        "Batch Create Rows",
        ["bulk", "insert", "multiple"],
    )
    table_id: int = TABLE_FIELD
    rows: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=200,
        title="Rows",
        description="Array of row objects keyed by field name.",
    )
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowBatchUpdateRow(TypedDict):
    """A row ID and the table-specific fields to update."""

    __pydantic_config__ = ConfigDict(extra="allow")
    id: Annotated[int, Field(ge=1)]


class BaserowBatchUpdateRowsConfig(BaseModel):
    operation: Literal["batch_update_rows"] = _op(
        "batch_update_rows", "Batch", "Batch Update Rows", ["bulk", "patch", "multiple"]
    )
    table_id: int = TABLE_FIELD
    rows: List[BaserowBatchUpdateRow] = Field(
        ...,
        min_length=1,
        max_length=200,
        title="Rows",
        description="Array of row objects; each requires an id and the fields to change.",
    )
    user_field_names: bool = Field(True, title="Use Field Names")


class BaserowBatchDeleteRowsConfig(BaseModel):
    operation: Literal["batch_delete_rows"] = _op(
        "batch_delete_rows",
        "Batch",
        "Batch Delete Rows",
        ["bulk", "remove", "multiple"],
    )
    table_id: int = TABLE_FIELD
    row_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=200,
        title="Row IDs",
        description="IDs of rows to remove.",
    )


BaserowOperation = Annotated[
    Union[
        BaserowListTablesConfig,
        BaserowListFieldsConfig,
        BaserowListRowsConfig,
        BaserowGetRowConfig,
        BaserowCreateRowConfig,
        BaserowUpdateRowConfig,
        BaserowMoveRowConfig,
        BaserowDeleteRowConfig,
        BaserowBatchCreateRowsConfig,
        BaserowBatchUpdateRowsConfig,
        BaserowBatchDeleteRowsConfig,
    ],
    Discriminator("operation"),
]


class BaserowNodeConfig(NodeConfig[BaserowOperation, BaserowCredential]):
    pass


class BaserowNode(WorkflowNode):
    """Read and write Baserow tables with a scoped database token."""

    integration_type = "automation-baserow"

    credential_provider_labels = {"baserow": "Baserow Account"}

    edit_examples = [
        "List the rows in my Baserow Customers table where Status is Active",
        "Create a Baserow row with the new lead's name and email",
        "Update the Status field of a Baserow row",
        "Batch create rows in a Baserow table from the previous step",
    ]
    connection_evidence = ConnectionEvidence(operation="list_tables", noun="tables")

    @classmethod
    def get_config_model(cls):
        return BaserowNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context=None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ):
        if field_name != "table_id":
            return {"options": []}
        credentials = BaserowDatabaseTokenCredential.model_validate(credential_data)
        result = await cls._request(
            "GET", "/database/tables/all-tables/", credentials, "list_tables"
        )
        if result["status"] != "success":
            return {"options": []}
        data = result["data"]
        tables = (
            data
            if isinstance(data, list)
            else data.get("tables", data.get("results", []))
        )
        options = [
            {
                "value": str(row["id"]),
                "label": row.get("name", str(row["id"])),
                "metadata": {"database_id": row.get("database_id")},
            }
            for row in tables
            if isinstance(row, dict)
            and "id" in row
            and (not search or search.casefold() in str(row.get("name", "")).casefold())
        ]
        return {"options": options}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, BaserowNodeConfig):
            raise ValueError("Valid Baserow configuration is required")
        config = self.config.config
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Connect a Baserow database token first")
        action = config.operation
        start = time.perf_counter()
        table = getattr(config, "table_id", None)
        row = getattr(config, "row_id", None)
        params: Dict[str, Any] = {}
        if hasattr(config, "user_field_names"):
            params["user_field_names"] = str(config.user_field_names).lower()
        path = f"/database/rows/table/{table}/"
        method = "GET"
        body = None
        if action == "list_tables":
            path = "/database/tables/all-tables/"
        elif action == "list_fields":
            path = f"/database/fields/table/{table}/"
        elif action == "list_rows":
            params.update(page=config.page, size=config.size)
            for key in ("search", "order_by", "view_id"):
                value = getattr(config, key)
                if value is not None:
                    params[key] = value
            if config.filters is not None:
                import json

                params["filters"] = json.dumps(config.filters)
        elif action in ("get_row", "update_row", "delete_row", "move_row"):
            path += f"{row}/"
            if action == "update_row":
                method, body = "PATCH", config.fields
            elif action == "delete_row":
                method = "DELETE"
            elif action == "move_row":
                method = "PATCH"
                path += "move/"
                if config.before_row_id is not None:
                    params["before_id"] = config.before_row_id
        elif action == "create_row":
            method, body = "POST", config.fields
            if config.before_row_id is not None:
                params["before"] = config.before_row_id
        elif action in ("batch_create_rows", "batch_update_rows"):
            path += "batch/"
            method = "POST" if action == "batch_create_rows" else "PATCH"
            body = {"items": config.rows}
        elif action == "batch_delete_rows":
            path += "batch-delete/"
            method, body = "POST", {"items": config.row_ids}
        else:
            raise ValueError(f"Unsupported Baserow operation: {action}")
        result = await self._request(
            method, path, credentials, action, params=params, body=body
        )
        result["timing_ms"]["total"] = round((time.perf_counter() - start) * 1000, 2)
        return result

    @staticmethod
    async def _request(
        method: str,
        path: str,
        credentials: BaserowDatabaseTokenCredential,
        action: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base = credentials.base_url.rstrip("/")
        parsed = urlparse(base)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Baserow URL must be a public HTTPS origin, without credentials or a path"
            )
        url = f"{base}/api{path}"
        start = time.perf_counter()
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=body,
                    headers={
                        "Authorization": f"Token {credentials.database_token}",
                        "Accept": "application/json",
                    },
                )
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            try:
                data = (
                    response.json()
                    if response.content
                    else {"deleted": response.is_success}
                )
            except ValueError:
                data = {"message": response.text[:500]}
            if response.is_error:
                detail = (
                    data.get("detail") or data.get("error")
                    if isinstance(data, dict)
                    else str(data)
                )
                return {
                    "status": "error",
                    "action": action,
                    "error": str(detail),
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": elapsed},
                }
            return {
                "status": "success",
                "action": action,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": elapsed},
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "status": "error",
                "action": action,
                "error": str(exc),
                "timing_ms": {
                    "api_request": round((time.perf_counter() - start) * 1000, 2)
                },
            }
