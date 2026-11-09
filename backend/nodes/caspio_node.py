"""Caspio REST v4 table records, schema discovery, views and task runs.

Contract: https://demo.caspio.com/integrations/rest/v4/swagger/documentation
Authentication: https://howto.caspio.com/integrate-your-apps/web-services-api/authenticating-rest/
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class CaspioBearerTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Caspio Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://howto.caspio.com/integrate-your-apps/web-services-api/authenticating-rest/",
            "x-credential-instructions": "Paste an existing access token from your Caspio API profile and its resource endpoint, ending in /rest. The profile must permit the tables, views and tasks you use. Access tokens expire after 24 hours; replace the token when it expires. NoClick does not generate or refresh tokens.",
        },
    )
    credential_type: Literal["caspio_bearer_token"] = Field("caspio_bearer_token", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="Resource endpoint", description="Your API profile's HTTPS resource endpoint, for example https://b1abc2.caspio.com/rest.")
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url")
    @classmethod
    def endpoint(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.caspio\.com", host)
                or parsed.netloc != host or parsed.query or parsed.fragment
                or parsed.path not in ({"/rest", "/integrations/rest"} if host == "demo.caspio.com" else {"/rest"})):
            raise ValueError("Use your Caspio HTTPS resource endpoint ending in /rest, without a query or version suffix")
        return value

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the access token, without the Bearer prefix")
        return value


ObjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{6}$", description="Six-character Caspio identifier returned by discovery; names are not identifiers.")]
RecordId = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=32, description="System PK_ID returned by Caspio, not a customer-defined key.")]


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Config):
    page_number: int = Field(1, ge=1, le=2147483647)
    page_size: int = Field(100, ge=1, le=1000, description="One explicit page; use pagination.totalCount to determine whether more pages remain.")


class ListTables(_Page):
    """Discover table IDs and names for this account."""
    operation: Literal["list_tables"] = "list_tables"
    table_name: str | None = Field(None, max_length=1000, description="Case-insensitive substring of the table name.")


class GetTable(_Config):
    """Get a table's design by its discovered ID."""
    operation: Literal["get_table"] = "get_table"
    table_id: ObjectId


class ListTableFields(_Page):
    """Discover field names, types and editability before querying or writing."""
    operation: Literal["list_table_fields"] = "list_table_fields"
    table_id: ObjectId


class GetTableField(_Config):
    """Get one field's definition using its name, not its display label."""
    operation: Literal["get_table_field"] = "get_table_field"
    table_id: ObjectId
    field_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("field_name")
    @classmethod
    def segment(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\\r\n\x00"):
            raise ValueError("Use a single field name returned by Caspio")
        return value


class _RecordPage(_Page):
    select: str | None = Field(None, max_length=8000, description="Comma-separated field names or T-SQL expressions; omitted means all fields.")
    where: str | None = Field(None, max_length=8000, description="SQL Server condition without WHERE, e.g. Status=N'Active'. Double embedded single quotes.")
    order_by: str | None = Field(None, max_length=8000, description="T-SQL ordering, e.g. LastName ASC, FirstName DESC.")
    group_by: str | None = Field(None, max_length=8000, description="GROUP BY clause for aggregate SELECT expressions.")


class ListTableRecords(_RecordPage):
    """Query a single page of table records."""
    operation: Literal["list_table_records"] = "list_table_records"
    table_id: ObjectId


class GetTableRecord(_Config):
    """Read one record by its system PK_ID."""
    operation: Literal["get_table_record"] = "get_table_record"
    table_id: ObjectId
    record_pk_id: RecordId


class _Values(_Config):
    values: dict[str, Any] = Field(..., min_length=1, title="Record values",
        description="Flat JSON object of editable field names and values. Discover fields first. Omit auto-generated fields and PK_ID. Use null to clear a field on update.",
        json_schema_extra={"ui:widget": "state_editor", "placeholder": '{\n  "Name": "Example"\n}'})

    @field_validator("values")
    @classmethod
    def record_values(cls, value):
        if any(not key or key.upper() == "PK_ID" for key in value):
            raise ValueError("Use editable field names; PK_ID is generated by Caspio")
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Provide JSON values with finite numbers") from None
        if len(encoded.encode()) > 1_000_000:
            raise ValueError("Record values exceed one megabyte")
        return value


class CreateTableRecord(_Values):
    """Insert a table record; returns its new PK_ID."""
    operation: Literal["create_table_record"] = "create_table_record"
    table_id: ObjectId


class UpdateTableRecord(_Values):
    """Patch only supplied fields, preserving omitted fields; returns affected count."""
    operation: Literal["update_table_record"] = "update_table_record"
    table_id: ObjectId
    record_pk_id: RecordId


class DeleteTableRecord(_Config):
    """Delete one table record by PK_ID; returns the affected count."""
    operation: Literal["delete_table_record"] = "delete_table_record"
    table_id: ObjectId
    record_pk_id: RecordId


class ListViews(_Page):
    """Discover account views and their identifiers."""
    operation: Literal["list_views"] = "list_views"
    view_name: str | None = Field(None, max_length=1000)


class GetView(_Config):
    """Get a view's design."""
    operation: Literal["get_view"] = "get_view"
    view_id: ObjectId


class ListViewFields(_Page):
    """Discover view field names, types and editability."""
    operation: Literal["list_view_fields"] = "list_view_fields"
    view_id: ObjectId


class ListViewRecords(_RecordPage):
    """Query a page from a single-table or joined view."""
    operation: Literal["list_view_records"] = "list_view_records"
    view_id: ObjectId


class GetViewRecord(_Config):
    """Read a view record, preserving composite PK_ID strings verbatim."""
    operation: Literal["get_view_record"] = "get_view_record"
    view_id: ObjectId
    record_pk_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[0-9]+(?:,[0-9]+)*$", description="Exact PK_ID from the view response; joins use comma-separated IDs.")


class ListTasks(_Page):
    """Discover account tasks."""
    operation: Literal["list_tasks"] = "list_tasks"
    task_name: str | None = Field(None, max_length=1000)


class GetTask(_Config):
    """Read a task's details."""
    operation: Literal["get_task"] = "get_task"
    task_id: ObjectId


class RunTask(_Config):
    """Run a task synchronously. A timeout does not prove it failed; inspect runs before retrying."""
    operation: Literal["run_task"] = "run_task"
    task_id: ObjectId


class ListTaskRuns(_Page):
    """List a task's execution history."""
    operation: Literal["list_task_runs"] = "list_task_runs"
    task_id: ObjectId
    page_size: int = Field(25, ge=5, le=1000)


class GetTaskRun(_Config):
    """Read one task run's details."""
    operation: Literal["get_task_run"] = "get_task_run"
    task_id: ObjectId
    run_id: UUID


CaspioOperation = Annotated[Union[
    ListTables, GetTable, ListTableFields, GetTableField, ListTableRecords,
    GetTableRecord, CreateTableRecord, UpdateTableRecord, DeleteTableRecord,
    ListViews, GetView, ListViewFields, ListViewRecords, GetViewRecord,
    ListTasks, GetTask, RunTask, ListTaskRuns, GetTaskRun,
], Field(discriminator="operation")]


class CaspioConfig(NodeConfig[CaspioOperation, CaspioBearerTokenCredential]):
    pass


# Each operation corresponds to exactly one published v4 contract operation.
ROUTES = {
    "list_tables": ("GET", "/tables"),
    "get_table": ("GET", "/tables/{table_id}"),
    "list_table_fields": ("GET", "/tables/{table_id}/fields"),
    "get_table_field": ("GET", "/tables/{table_id}/fields/{field_name}"),
    "list_table_records": ("GET", "/tables/{table_id}/records"),
    "get_table_record": ("GET", "/tables/{table_id}/records/{record_pk_id}"),
    "create_table_record": ("POST", "/tables/{table_id}/records"),
    "update_table_record": ("PATCH", "/tables/{table_id}/records/{record_pk_id}"),
    "delete_table_record": ("DELETE", "/tables/{table_id}/records/{record_pk_id}"),
    "list_views": ("GET", "/views"),
    "get_view": ("GET", "/views/{view_id}"),
    "list_view_fields": ("GET", "/views/{view_id}/fields"),
    "list_view_records": ("GET", "/views/{view_id}/records"),
    "get_view_record": ("GET", "/views/{view_id}/records/{record_pk_id}"),
    "list_tasks": ("GET", "/tasks"),
    "get_task": ("GET", "/tasks/{task_id}"),
    "run_task": ("POST", "/tasks/{task_id}/run"),
    "list_task_runs": ("GET", "/tasks/{task_id}/runs"),
    "get_task_run": ("GET", "/tasks/{task_id}/runs/{run_id}"),
}


class CaspioNode(WorkflowNode):
    integration_type = "automation-caspio"
    connection_evidence = ConnectionEvidence(noun="Caspio tables", operation="list_tables", label_keys=("name", "tableId"))

    @classmethod
    def get_config_model(cls):
        return CaspioConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a Caspio bearer token"}
        config = self.config.config
        method, template = ROUTES[config.operation]
        route = template.format(**{key: quote(str(value), safe="") for key, value in config.model_dump().items()})
        params = {}
        if isinstance(config, _Page):
            # Record query parameters are PascalCase; metadata lists use camelCase.
            prefix = "P" if isinstance(config, _RecordPage) else "p"
            params = {prefix + "ageNumber": config.page_number, prefix + "ageSize": config.page_size}
        for source, target in {"table_name": "tableName", "view_name": "viewName", "task_name": "taskName",
                               "select": "Select", "where": "Where", "order_by": "OrderBy", "group_by": "GroupBy"}.items():
            value = getattr(config, source, None)
            if value is not None:
                params[target] = value
        kwargs = {"json": config.values} if isinstance(config, _Values) else {}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, credential.api_base_url + "/v4" + route,
                    params=params, headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, **kwargs)
            if response.status_code not in {200, 201}:
                # Preserve the provider's rejection text, excluding the secret if echoed.
                message = response.text[:2000].replace(credential.access_token, "[redacted]")
                return {"status": "error", "http_status": response.status_code, "error": message or "Caspio rejected the request"}
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected a JSON response of at most ten megabytes from Caspio")
            body = response.json()
            if not isinstance(body, dict) or any(key in body for key in ("error", "errors", "Error", "Errors")):
                raise ValueError("Caspio returned an unexpected response")
            return {**body, "status": "success", "operation": config.operation, "http_status": response.status_code}
        except httpx.TimeoutException:
            return {"status": "error", "error": "Caspio request timed out; a write may have completed. Inspect the record or task runs before retrying."}
        except httpx.HTTPError:
            return {"status": "error", "error": "Could not complete the Caspio request; a write may have completed. Inspect before retrying."}
        except ValueError as exc:
            return {"status": "error", "error": str(exc).replace(credential.access_token, "[redacted]")}
