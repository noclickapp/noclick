"""Rocketadmin API+ operations. Contract: https://app.rocketadmin.com/api/docs-json (1.0).

Primary keys are query parameters as in the provider's pure CRUD controller:
https://github.com/rocket-admin/rocketadmin/blob/main/backend/src/entities/table/table-pure-crud-operations/table-pure-crud-operations.controller.ts
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.rocketadmin.com/api"
JsonObject = Union[dict[str, Any], Json[dict[str, Any]]]


class RocketadminAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rocketadmin API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.rocketadmin.com/",
        "x-credential-instructions": "In Rocketadmin, open your profile's API Keys page, create a key, and paste it here. The key uses your account's database permissions. For a connection encrypted with a master password, also supply that password."})
    credential_type: Literal["rocketadmin_api_key"] = Field("rocketadmin_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    master_password: str | None = Field(None, title="Master password", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "master_password", mode="before")
    @classmethod
    def secret(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Rocketadmin secret")
        if any(c in value for c in "\r\n"):
            raise ValueError("Paste the secret without line breaks")
        return value


def _op(name, title, category="Tables"):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True,
        "x-display-name": title, "x-category": category, "x-is-trigger": False})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListConnections(_Input):
    operation: Literal["list_connections"] = _op("list_connections", "List Connections", "Connections")


class _Connection(_Input):
    connection_id: str = Field(..., min_length=1, max_length=200, title="Connection ID", description="ID from List Connections.")

    @field_validator("connection_id")
    @classmethod
    def safe_segment(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
            raise ValueError("Use a single Rocketadmin connection ID")
        return value


class ListTables(_Connection):
    operation: Literal["list_tables"] = _op("list_tables", "List Tables")
    hidden: Literal["true", "false"] | None = Field(None, title="Include hidden tables")


class ListTablesWithCategories(ListTables):
    operation: Literal["list_tables_with_categories"] = _op("list_tables_with_categories", "List Tables with Categories")


class _Table(_Connection):
    table_name: str = Field(..., min_length=1, title="Table name", description="Exact database table name returned by List Tables.")


class GetTableStructure(_Table):
    operation: Literal["get_table_structure"] = _op("get_table_structure", "Get Table Structure")


class GetTableStructureUncached(_Table):
    operation: Literal["get_table_structure_uncached"] = _op("get_table_structure_uncached", "Get Table Structure without Cache")


class ListRows(_Table):
    operation: Literal["list_rows"] = _op("list_rows", "List Rows", "Rows")
    filters: JsonObject = Field(default_factory=dict, title="Filters", description='Column filters as JSON, for example {"id":{"eq":1}}. Empty object lists all rows.')
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(20, ge=1, le=1000, title="Rows per page")
    search: str | None = Field(None, title="Search")


class _SelectedRow(_Table):
    primary_key: Union[dict[str, str | int | float | bool], Json[dict[str, str | int | float | bool]]] = Field(
        ..., min_length=1, title="Primary key", description='JSON object keyed by all primary-key column names, for example {"id":123}.')

    @field_validator("primary_key")
    @classmethod
    def reserved_keys(cls, value):
        if any(k in {"tableName", "page", "perPage", "search"} for k in value):
            raise ValueError("Primary-key columns must not collide with API query parameters")
        return value


class GetRow(_SelectedRow):
    operation: Literal["get_row"] = _op("get_row", "Get Row", "Rows")


class CreateRow(_Table):
    operation: Literal["create_row"] = _op("create_row", "Create Row", "Rows")
    values: JsonObject = Field(..., min_length=1, title="Column values", description="JSON object of column names and values to insert.")


class UpdateRow(_SelectedRow):
    operation: Literal["update_row"] = _op("update_row", "Update Row", "Rows")
    values: JsonObject = Field(..., min_length=1, title="Column values", description="JSON object of column names and new values.")


class DeleteRow(_SelectedRow):
    operation: Literal["delete_row"] = _op("delete_row", "Delete Row", "Rows")


RocketadminConfig = Annotated[Union[ListConnections, ListTables, ListTablesWithCategories,
    GetTableStructure, GetTableStructureUncached, ListRows, GetRow, CreateRow, UpdateRow, DeleteRow], Field(discriminator="operation")]


class RocketadminNodeConfig(NodeConfig[RocketadminConfig, RocketadminAPIKeyCredential]):
    pass


ROUTES = {
    "list_connections": ("GET", "/connections"),
    "list_tables": ("GET", "/connection/tables/{connection_id}"),
    "list_tables_with_categories": ("GET", "/connection/tables/v2/{connection_id}"),
    "get_table_structure": ("GET", "/table/structure/{connection_id}"),
    "get_table_structure_uncached": ("GET", "/table/structure/no-cache/{connection_id}"),
    "list_rows": ("POST", "/table/crud/rows/{connection_id}"),
    "get_row": ("GET", "/table/crud/{connection_id}"),
    "create_row": ("POST", "/table/crud/{connection_id}"),
    "update_row": ("PUT", "/table/crud/{connection_id}"),
    "delete_row": ("DELETE", "/table/crud/{connection_id}"),
}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.master_password):
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


class RocketadminNode(WorkflowNode):
    integration_type = "automation-rocketadmin"
    connection_evidence = ConnectionEvidence(operation="list_connections", noun="database connections", label_keys=("title", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return RocketadminNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Rocketadmin API key")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        path = path.format(connection_id=quote(getattr(config, "connection_id", ""), safe=""))
        params, body = {}, None
        if isinstance(config, _Table):
            params["tableName"] = config.table_name
        if isinstance(config, ListTables) and config.hidden is not None:
            params["hidden"] = config.hidden
        if isinstance(config, _SelectedRow):
            params.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.primary_key.items()})
        if isinstance(config, ListRows):
            params.update(page=str(config.page), perPage=str(config.per_page))
            if config.search is not None:
                params["search"] = config.search
            body = {"filters": config.filters}
        if isinstance(config, (CreateRow, UpdateRow)):
            body = config.values
        headers = {"x-api-key": credential.api_key, "Accept": "application/json"}
        if credential.master_password:
            headers["masterpwd"] = credential.master_password
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, headers=headers,
                **({"json": body} if body is not None else {}))
        expected = 201 if config.operation == "create_row" else 200
        if response.status_code != expected:
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            if not isinstance(message, str):
                message = "Rocketadmin request failed"
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, credential)}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Rocketadmin returned an invalid JSON response") from None
        if isinstance(data, dict) and data.get("error"):
            raise ValueError("Rocketadmin returned an error response")
        if config.operation == "list_connections":
            if not isinstance(data, dict) or not isinstance(data.get("connections"), list):
                raise ValueError("Rocketadmin returned an invalid connection list")
            if any(not isinstance(item, dict) or not isinstance(item.get("connection"), dict) for item in data["connections"]):
                raise ValueError("Rocketadmin returned an invalid connection")
            result = {"data": data, "items": [item["connection"] for item in data["connections"]]}
        elif config.operation == "list_tables":
            if not isinstance(data, list):
                raise ValueError("Rocketadmin returned an invalid table list")
            result = {"data": data}
        elif config.operation == "list_tables_with_categories":
            if not isinstance(data, dict) or not isinstance(data.get("tables"), list):
                raise ValueError("Rocketadmin returned invalid table categories")
            result = {"data": data}
        elif config.operation.startswith("get_table_structure"):
            if not isinstance(data, dict) or not isinstance(data.get("structure"), list):
                raise ValueError("Rocketadmin returned an invalid table structure")
            result = {"data": data}
        elif config.operation == "list_rows":
            if not isinstance(data, dict) or not isinstance(data.get("rows"), list) or not isinstance(data.get("pagination"), dict):
                raise ValueError("Rocketadmin returned an invalid rows page")
            result = {"rows": data["rows"], "pagination": data["pagination"]}
        else:
            if not isinstance(data, dict) or not isinstance(data.get("row"), dict):
                raise ValueError("Rocketadmin returned an invalid row")
            result = {"row": data["row"]}
        return _redact({"status": "success", **result}, credential)
