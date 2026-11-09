"""Method CRM table and file automation using a person's pasted API key.

Each operation makes one request to the published REST v1 contract. Table
records keep their account-specific field names and paging stays explicit.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.method.me/api/v1"


class MethodCRMAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Method CRM API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://rest.method.me/#section/Authentication",
            "x-credential-instructions": "In Method, open Integrations → API → API keys → New. Generate and copy the API key, then paste it here without the APIKey prefix.",
        })
    credential_type: Literal["method_crm_api_key"] = Field("method_crm_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the APIKey prefix or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Table(_Operation):
    table: str = Field(..., min_length=1, description="Exact table name from List Tables, e.g. Contacts, Customer, Activity or Invoice.")

    @field_validator("table")
    @classmethod
    def table_name(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
            raise ValueError("Use a table name, without URL separators")
        return value


class _Record(_Table):
    record_id: int = Field(..., ge=1, le=2147483647, description="RecordID of the selected table row.")


class _Write(_Table):
    record_json: str = Field(..., description="JSON object with exact case-sensitive, writable field names from Get Table Fields. Linked fields use their foreign-key IDs. Aggregate writes allow up to 50 children and require a parent field.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("record_json")
    @classmethod
    def record_body(cls, value):
        try:
            body = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        except (ValueError, TypeError):
            raise ValueError("Enter a valid JSON record object") from None
        if not isinstance(body, dict) or not body or not any(not k.startswith("__") for k in body):
            raise ValueError("Include at least one parent record field")
        children = [v for k, v in body.items() if k.startswith("__")]
        if any(not isinstance(v, list) or any(not isinstance(row, dict) for row in v) for v in children):
            raise ValueError("Related tables must be arrays of record objects")
        if sum(len(v) for v in children) > 50:
            raise ValueError("Send at most 50 related records per request")
        return value


class ListTablesConfig(_Operation):
    """List the tables and custom tables available to this account."""
    operation: Literal["list_tables"] = "list_tables"


class GetTableFieldsConfig(_Table):
    """Get field names, types and account-specific write permissions."""
    operation: Literal["get_table_fields"] = "get_table_fields"


class QueryRecordsConfig(_Table):
    """Query one page of contacts, customers, activities or any account table."""
    operation: Literal["query_records"] = "query_records"
    select: str | None = Field(None, description="Comma-separated field names.")
    filter: str | None = Field(None, description="Method filter expression; include Z or an offset for dates.")
    orderby: str | None = Field(None, description="Comma-separated ordering, e.g. RecordID asc.")
    apply: str | None = Field(None, description="Documented aggregation expression.")
    top: int = Field(10, ge=1, le=100, description="Page size. Read next_link and advance skip for another page.")
    skip: int = Field(0, ge=0, le=2147483647)


class GetRecordConfig(_Record):
    """Read a record with optional selected and expanded fields."""
    operation: Literal["get_record"] = "get_record"
    select: str | None = None
    expand: str | None = Field(None, description="Linked fields to expand, e.g. Entity.")


class CreateRecordConfig(_Write):
    """Create a contact, customer, lead, activity, invoice or custom record."""
    operation: Literal["create_record"] = "create_record"


class UpdateRecordConfig(_Write, _Record):
    """Patch a record; omitted fields and child records remain unchanged."""
    operation: Literal["update_record"] = "update_record"


class DeleteRecordConfig(_Record):
    """Delete the selected table record."""
    operation: Literal["delete_record"] = "delete_record"


class CountRecordsConfig(_Table):
    """Count all records or records matching a filter."""
    operation: Literal["count_records"] = "count_records"
    filter: str | None = None


class SyncRecordConfig(_Record):
    """Force a syncable record to QuickBooks or Xero, overriding normal timing."""
    operation: Literal["sync_record"] = "sync_record"


class ListFilesConfig(_Operation):
    """List files, optionally restricted to a table and record."""
    operation: Literal["list_files"] = "list_files"
    table: str | None = None
    record_id: int | None = Field(None, ge=1, le=2147483647)


class _File(_Operation):
    file_id: str = Field(..., min_length=1, description="File id returned by List Files.")

    @field_validator("file_id")
    @classmethod
    def file_identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
            raise ValueError("Use a file ID, without URL separators")
        return value


class GetFileURLConfig(_File):
    """Retrieve the provider's file URL without downloading it."""
    operation: Literal["get_file_url"] = "get_file_url"


class UpdateFileLinkConfig(_File, _Record):
    """Update the file link's attach-to-email flag for a table record."""
    operation: Literal["update_file_link"] = "update_file_link"
    attach_to_email: bool = Field(..., description="Whether the linked file is attached to email.")


class DeleteFileConfig(_File):
    """Delete a file by its provider ID."""
    operation: Literal["delete_file"] = "delete_file"


MethodCRMConfig = Annotated[Union[ListTablesConfig, GetTableFieldsConfig, QueryRecordsConfig,
    GetRecordConfig, CreateRecordConfig, UpdateRecordConfig, DeleteRecordConfig,
    CountRecordsConfig, SyncRecordConfig, ListFilesConfig, GetFileURLConfig,
    UpdateFileLinkConfig, DeleteFileConfig], Field(discriminator="operation")]


class MethodCRMFullConfig(NodeConfig[MethodCRMConfig, MethodCRMAPIKeyCredential]):
    pass


def _request_parts(op):
    name = op.operation
    if name == "list_tables":
        return "GET", "/tables", {}, None
    if name == "list_files":
        return "GET", "/files", {k: v for k, v in {"table": op.table, "recordId": op.record_id}.items() if v is not None}, None
    if isinstance(op, _File):
        path = "/files/" + quote(op.file_id, safe="")
        if name == "get_file_url":
            return "GET", path + "/url", {}, None
        if name == "update_file_link":
            return "PUT", path + "/link", {}, {"tableName": op.table, "recordId": op.record_id, "attachToEmail": op.attach_to_email}
        return "DELETE", path, {}, None
    path = "/tables/" + quote(op.table, safe="")
    if name == "get_table_fields":
        return "GET", path + "/fields", {}, None
    if name == "query_records":
        return "GET", path, {k: getattr(op, k) for k in ("select", "filter", "orderby", "apply", "top", "skip") if getattr(op, k) is not None}, None
    if name == "count_records":
        return "GET", path + "/count", {"filter": op.filter} if op.filter is not None else {}, None
    if name == "create_record":
        return "POST", path, {}, json.loads(op.record_json)
    path += "/" + str(op.record_id)
    if name == "get_record":
        return "GET", path, {k: getattr(op, k) for k in ("select", "expand") if getattr(op, k) is not None}, None
    if name == "update_record":
        return "PATCH", path, {}, json.loads(op.record_json)
    if name == "sync_record":
        return "POST", path + "/Sync", {}, None
    return "DELETE", path, {}, None


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


class MethodCRMNode(WorkflowNode):
    integration_type = "automation-method-crm"
    connection_evidence = ConnectionEvidence(noun="tables", operation="list_tables")

    @classmethod
    def get_config_model(cls):
        return MethodCRMFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Method CRM API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, params, body = _request_parts(op)
        kwargs = {"params": params, "headers": {"Authorization": "APIKey " + key, "Accept": "application/json"}}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("detail") or error.get("title") or message
            except ValueError:
                pass
            raise ValueError(f"Method CRM HTTP {response.status_code}: {_redact(str(message), key)}")
        if response.status_code == 204:
            return {"success": True}
        data = _redact(response.json(), key)
        if isinstance(data, dict) and ("errors" in data or data.get("status", 0) in range(400, 600)):
            raise ValueError("Method CRM: " + str(data.get("detail") or data.get("title") or "Request rejected"))
        name = op.operation
        if name in {"list_tables", "query_records"}:
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise ValueError("Method CRM returned an invalid record list")
            result = {"items": data["value"], "count": data.get("count")}
            if name == "query_records":
                # Return the provider link as metadata; never follow a response URL.
                result["next_link"] = data.get("nextLink")
            return result
        if name == "create_record":
            if type(data) is not int:
                raise ValueError("Method CRM did not return a RecordID")
            return {"record_id": data}
        if name == "count_records":
            if type(data) is not int:
                raise ValueError("Method CRM did not return a record count")
            return {"count": data}
        if name == "get_file_url":
            if not isinstance(data, str):
                raise ValueError("Method CRM did not return a file URL")
            return {"url": data}
        if name == "list_files":
            if not isinstance(data, list):
                raise ValueError("Method CRM returned an invalid file list")
            return {"items": data}
        if not isinstance(data, dict):
            raise ValueError("Method CRM returned an invalid record")
        return {"data": data}
