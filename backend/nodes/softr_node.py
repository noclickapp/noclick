"""Softr Database API v1: one documented request per operation.

Uses a pasted Softr API key, fixed provider origin and explicit pagination.
Contract: https://docs.softr.io/openapi.yaml (1.0.0).
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://tables-api.softr.io/api/v1"
ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


def _json_field(kind, description, default=...):
    schema = {"type": kind}
    if kind == "array":
        schema["items"] = {"type": "object", "properties": {
            "sortingField": {"type": "string"}, "sortType": {"type": "string", "enum": ["ASC", "DESC"]}}}
    return Field(default, description=description, max_length=100000,
        json_schema_extra={"ui:widget": "code_editor", "ui:options": {"language": "json"},
            "contentMediaType": "application/json", "contentSchema": schema})


def _decode(value, kind):
    try:
        result = json.loads(value)
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError):
        raise ValueError("Enter valid JSON") from None
    if not isinstance(result, kind):
        raise ValueError("JSON must be an object" if kind is dict else "JSON must be an array")
    if kind is list:
        for item in result:
            if not isinstance(item, dict) or ("sortingField" in item and not isinstance(item["sortingField"], str)) or ("sortType" in item and item["sortType"] not in ("ASC", "DESC")):
                raise ValueError("Sorting entries must be objects with sortingField and ASC or DESC sortType")
    return result


class SoftrAPIKey(BaseModel):
    model_config = ConfigDict(title="Softr API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.softr.io/softr-api",
            "x-credential-instructions": "Paste your Softr API key or personal access token with access to the databases you want to automate. Enable write access for create, update and delete actions. NoClick sends it in the Softr-Api-Key header to tables-api.softr.io. List databases checks the databases visible to this key."})
    credential_type: Literal["softr_api_key"] = Field("softr_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key or personal access token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the API key or token, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("fields_json", "condition_json", "sorting_json", "options_json", check_fields=False)
    @classmethod
    def json_values(cls, value, info):
        if value is not None:
            _decode(value, list if info.field_name == "sorting_json" else dict)
        return value


class _Database(_Input):
    database_id: ResourceID = Field(..., title="Database ID")


class _Table(_Database):
    table_id: ResourceID = Field(..., title="Table ID")


class _Record(_Table):
    record_id: ResourceID = Field(..., title="Record ID")


class _Field(_Table):
    field_id: ResourceID = Field(..., title="Field ID")


class ListDatabases(_Input):
    """Get Databases. Retrieve a list of all databases accessible to the authenticated user."""
    operation: Literal["list_databases"] = "list_databases"

class GetDatabase(_Database):
    """Get Single Database. Retrieve details of a specific database by its ID."""
    operation: Literal["get_database"] = "get_database"

class CreateDatabase(_Input):
    """Create a Database. Create a new database in the specified workspace."""
    operation: Literal["create_database"] = "create_database"
    workspace_id: ResourceID
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None

class UpdateDatabase(_Database):
    """Update Database. Update the details of an existing database."""
    operation: Literal["update_database"] = "update_database"
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None

class DeleteDatabase(_Database):
    """Delete Database. Delete a specific database by its ID. It can only be deleted if it is empty, unless the 'force' parameter is used."""
    operation: Literal["delete_database"] = "delete_database"
    force: bool = Field(False, description="Delete even when the database is not empty. Destructive.")

class ListTables(_Database):
    """Get Tables. Retrieve a list of all tables in the specified database."""
    operation: Literal["list_tables"] = "list_tables"

class GetTable(_Table):
    """Get Single Table. Retrieve details of a specific table by its ID."""
    operation: Literal["get_table"] = "get_table"

class CreateTable(_Database):
    """Create Table. Create a new table in the specified database."""
    operation: Literal["create_table"] = "create_table"
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None
    primary_field_name: str | None = None

class UpdateTable(_Table):
    """Update Table. Update a table's name and/or description. To modify fields, use the field-specific endpoints."""
    operation: Literal["update_table"] = "update_table"
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None

class DeleteTable(_Table):
    """Delete Table. Delete a specific table by its ID. It can only be deleted if it is empty, unless the 'force' parameter is used."""
    operation: Literal["delete_table"] = "delete_table"
    force: bool = Field(False, description="Delete even when the table is not empty. Destructive.")

class ListTableViews(_Table):
    """Get Table Views. Retrieve a list of views for a specific table."""
    operation: Literal["list_table_views"] = "list_table_views"

class AddTableField(_Table):
    """Add Table Field. Add a new field to a table."""
    operation: Literal["add_table_field"] = "add_table_field"
    name: str = Field(..., min_length=1, max_length=1000)
    field_type: str = Field(..., min_length=1, description="Softr field type, for example SINGLE_LINE_TEXT or NUMBER.")
    options_json: str | None = _json_field("object", "Field options as a JSON object.", None)

class GetTableField(_Field):
    """Get Table Field. Retrieve details of a specific field."""
    operation: Literal["get_table_field"] = "get_table_field"

class UpdateTableField(_Field):
    """Update Table Field. Update the properties of a specific field."""
    operation: Literal["update_table_field"] = "update_table_field"
    name: str = Field(..., min_length=1, max_length=1000)
    field_type: str | None = None
    options_json: str | None = _json_field("object", "Field options as a JSON object.", None)

class DeleteTableField(_Field):
    """Delete Table Field. Delete a specific field from a table."""
    operation: Literal["delete_table_field"] = "delete_table_field"

class ListRecords(_Table):
    """Get Records. Retrieve a list of all records in the specified table."""
    operation: Literal["list_records"] = "list_records"
    offset: int = Field(0, ge=0)
    limit: int = Field(10, ge=1, le=100)
    field_names: bool = False
    view_id: ResourceID | None = None

class GetRecord(_Record):
    """Get Single Record. Retrieve details of a specific record by its ID."""
    operation: Literal["get_record"] = "get_record"
    field_names: bool = False

class CreateRecord(_Table):
    """Create Record. Create a new record in the specified table."""
    operation: Literal["create_record"] = "create_record"
    fields_json: str = _json_field("object", "Map of field IDs to values, as a JSON object.")
    field_names: bool = False

class UpdateRecord(_Record):
    """Update Record. Partially update a specific record by its ID. Only the fields provided in the request body will be changed."""
    operation: Literal["update_record"] = "update_record"
    fields_json: str = _json_field("object", "Only supplied field IDs are updated; use JSON null to clear a value.")
    field_names: bool = False

class DeleteRecord(_Record):
    """Delete Record. Delete a specific record by its ID."""
    operation: Literal["delete_record"] = "delete_record"

class SearchRecords(_Table):
    """Search Records. Search for records in the specified table based on filter, sort, and pagination criteria."""
    operation: Literal["search_records"] = "search_records"
    condition_json: str | None = _json_field("object", "Softr filter condition object: operator, leftSide, rightSide or nested conditions.", None)
    sorting_json: str | None = _json_field("array", "JSON array of sortingField and sortType (ASC or DESC) objects.", None)
    offset: int = Field(0, ge=0)
    limit: int = Field(10, ge=1, le=100)
    field_names: bool = False


SoftrOperation = Annotated[Union[ListDatabases, GetDatabase, CreateDatabase, UpdateDatabase, DeleteDatabase, ListTables, GetTable, CreateTable, UpdateTable, DeleteTable, ListTableViews, AddTableField, GetTableField, UpdateTableField, DeleteTableField, ListRecords, GetRecord, CreateRecord, UpdateRecord, DeleteRecord, SearchRecords], Field(discriminator="operation")]


class SoftrConfig(NodeConfig[SoftrOperation, SoftrAPIKey]):
    pass


ROUTES = {'list_databases': ('GET', '/databases'),
 'get_database': ('GET', '/databases/{database_id}'),
 'create_database': ('POST', '/databases'),
 'update_database': ('PUT', '/databases/{database_id}'),
 'delete_database': ('DELETE', '/databases/{database_id}'),
 'list_tables': ('GET', '/databases/{database_id}/tables'),
 'get_table': ('GET', '/databases/{database_id}/tables/{table_id}'),
 'create_table': ('POST', '/databases/{database_id}/tables'),
 'update_table': ('PUT', '/databases/{database_id}/tables/{table_id}'),
 'delete_table': ('DELETE', '/databases/{database_id}/tables/{table_id}'),
 'list_table_views': ('GET', '/databases/{database_id}/tables/{table_id}/views'),
 'add_table_field': ('POST', '/databases/{database_id}/tables/{table_id}/fields'),
 'get_table_field': ('GET', '/databases/{database_id}/tables/{table_id}/fields/{field_id}'),
 'update_table_field': ('PUT', '/databases/{database_id}/tables/{table_id}/fields/{field_id}'),
 'delete_table_field': ('DELETE', '/databases/{database_id}/tables/{table_id}/fields/{field_id}'),
 'list_records': ('GET', '/databases/{database_id}/tables/{table_id}/records'),
 'get_record': ('GET', '/databases/{database_id}/tables/{table_id}/records/{record_id}'),
 'create_record': ('POST', '/databases/{database_id}/tables/{table_id}/records'),
 'update_record': ('PATCH', '/databases/{database_id}/tables/{table_id}/records/{record_id}'),
 'delete_record': ('DELETE', '/databases/{database_id}/tables/{table_id}/records/{record_id}'),
 'search_records': ('POST', '/databases/{database_id}/tables/{table_id}/records/search')}


class SoftrNode(WorkflowNode):
    integration_type = "automation-softr"
    connection_evidence = ConnectionEvidence(operation="list_databases", noun="databases")

    @classmethod
    def get_config_model(cls):
        return SoftrConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Softr API key or personal access token")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in path:
                path = path.replace(marker, quote(values.pop(name), safe=""))
        params = {}
        aliases = {"workspace_id": "workspaceId", "primary_field_name": "primaryFieldName", "field_type": "type"}
        for name in ("field_names", "view_id", "force"):
            if name in values:
                value = values.pop(name)
                params[{"field_names": "fieldNames", "view_id": "viewId"}.get(name, name)] = str(value).lower() if isinstance(value, bool) else value
        if method == "GET":
            params.update(values)
            body = None
        else:
            body = {aliases.get(k, k): v for k, v in values.items()}
            for name in ("fields_json", "options_json"):
                if name in body:
                    body[name.removesuffix("_json")] = _decode(body.pop(name), dict)
            if op.operation == "search_records":
                body["paging"] = {"offset": body.pop("offset"), "limit": body.pop("limit")}
                if "condition_json" in body:
                    body["filter"] = {"condition": _decode(body.pop("condition_json"), dict)}
                if "sorting_json" in body:
                    body["sorting"] = _decode(body.pop("sorting_json"), list)
        token = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Softr-Api-Key": token, "Accept": "application/json"}, params=params,
                    **({"json": body} if method not in {"GET", "DELETE"} else {}))
        except httpx.HTTPError:
            raise ValueError("Softr request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            detail = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = str(error.get("message", "")).replace(token, "[redacted]")[:2000]
            except ValueError:
                pass
            raise ValueError(f"Softr rejected the request (HTTP {response.status_code}): {detail}")
        if method == "DELETE":
            if response.status_code != 204:
                raise ValueError("Softr did not return the documented deletion acknowledgement")
            return {"status": "success", "deleted": True, "http_status": 204}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Softr returned non-JSON data") from None
        if not isinstance(payload, dict) or "error" in payload or "errorCode" in payload:
            raise ValueError("Softr returned an invalid response envelope")
        expected = list if op.operation.startswith("list_") or op.operation == "search_records" else dict
        if not isinstance(payload.get("data"), expected):
            raise ValueError("Softr returned an unexpected data shape")
        result = {"status": "success", "data": payload["data"]}
        if op.operation in {"list_records", "search_records"}:
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError("Softr omitted record pagination metadata")
            result["metadata"] = metadata
        return result
