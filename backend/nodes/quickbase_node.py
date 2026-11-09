"""Quickbase REST v1 operations authenticated with a person's user token.

Requests target the published API host and preserve field-ID keyed records and
provider pagination metadata, including partial upsert failures.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


Dbid = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_]+$")]
FieldId = Annotated[int, Field(gt=0)]


def _json_input(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            raise ValueError("Enter a valid JSON array") from None
    return value


JsonFieldIds = Annotated[list[FieldId], BeforeValidator(_json_input, json_schema_input_type=str)]
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


def _filter_input(value):
    return _json_input(value) if isinstance(value, str) and value.lstrip().startswith("[") else value


RecordFilter = Annotated[
    Annotated[str, Field(min_length=1)] | Annotated[list[int], Field(min_length=1, max_length=50000)],
    BeforeValidator(_filter_input, json_schema_input_type=str),
]


class QuickbaseUserTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Quickbase User Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.quickbase.com/docs/create-and-use-user-tokens",
            "x-credential-instructions": "Create a user token in My preferences > My user information > Manage my user tokens, and assign it to the apps you need. Paste the token without QB-USER-TOKEN. Enter your realm hostname and an app ID the token can read; NoClick reads that app to check the connection. App access and your Quickbase permissions determine which operations are allowed.",
        },
    )
    credential_type: Literal["quickbase_user_token"] = Field("quickbase_user_token", json_schema_extra={"ui:hidden": True})
    user_token: str = Field(..., title="User token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    realm_hostname: str = Field(..., title="Realm hostname", description="Your realm hostname, for example demo.quickbase.com, without https:// or a path.")
    app_id: Dbid = Field(..., title="Connection app ID", description="An existing app assigned to this token. Find its ID in the app URL after /db/.")

    @field_validator("user_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="User token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the user token without a header or whitespace")
        return value

    @field_validator("realm_hostname", mode="before")
    @classmethod
    def realm(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.quickbase\.com", value.strip()):
            raise ValueError("Enter a realm hostname such as demo.quickbase.com")
        return value.strip().lower()


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _App(_Input):
    app_id: Dbid | None = Field(None, description="App ID. Defaults to the connection app ID.")


class GetApp(_App):
    """Read an app's metadata and name."""
    operation: Literal["get_app"] = "get_app"


class CreateApp(_Input):
    """Create an app; optionally assign it to this token."""
    operation: Literal["create_app"] = "create_app"
    name: str = Field(..., min_length=1)
    description: str | None = None
    assign_token: bool = Field(False, description="Assign the newly created app to the user token.")


class UpdateApp(_App):
    """Update an app's name or description."""
    operation: Literal["update_app"] = "update_app"
    name: str | None = None
    description: str | None = None


class ListAppEvents(_App):
    """List webhooks, notifications and other app events."""
    operation: Literal["list_app_events"] = "list_app_events"


class ListTables(_App):
    """List the tables in an app."""
    operation: Literal["list_tables"] = "list_tables"


class CreateTable(_App):
    """Create a named table in an app."""
    operation: Literal["create_table"] = "create_table"
    name: str = Field(..., min_length=1)
    description: str | None = None
    single_record_name: str | None = None
    plural_record_name: str | None = None


class _Table(_Input):
    table_id: Dbid = Field(..., description="Table database ID from its Quickbase URL.")


class GetTable(_Table, _App):
    """Read a table's metadata in its parent app."""
    operation: Literal["get_table"] = "get_table"


class UpdateTable(_Table, _App):
    """Update a table's name, description or record labels."""
    operation: Literal["update_table"] = "update_table"
    name: str | None = None
    description: str | None = None
    single_record_name: str | None = None
    plural_record_name: str | None = None


class ListReports(_Table):
    """List saved reports for a table."""
    operation: Literal["list_reports"] = "list_reports"


class _Report(_Table):
    report_id: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9]+$")


class GetReport(_Report):
    """Read a saved report definition."""
    operation: Literal["get_report"] = "get_report"


class RunReport(_Report):
    """Run one page of a saved report."""
    operation: Literal["run_report"] = "run_report"
    skip: int = Field(0, ge=0)
    top: int = Field(100, ge=1, le=10000)


class ListFields(_Table):
    """Read field definitions, optionally including field permissions."""
    operation: Literal["list_fields"] = "list_fields"
    include_field_perms: bool = False


class _Field(_Table):
    field_id: FieldId


class GetField(_Field):
    """Read one field definition."""
    operation: Literal["get_field"] = "get_field"
    include_field_perms: bool = False


class CreateField(_Table):
    """Create a field using one of the documented field types."""
    operation: Literal["create_field"] = "create_field"
    label: str = Field(..., min_length=1)
    field_type: Literal["text", "text-multiple-choice", "text-multi-line", "rich-text", "numeric", "currency", "rating", "percent", "multitext", "email", "url", "duration", "date", "datetime", "timestamp", "timeofday", "checkbox", "user", "multiuser", "address", "phone", "file"]
    field_help: str | None = None


class UpdateField(_Field):
    """Update a field's label or help text."""
    operation: Literal["update_field"] = "update_field"
    label: str | None = None
    field_help: str | None = None


class ListFieldUsage(_Table):
    """Read report, form and other usage of a table's fields."""
    operation: Literal["list_field_usage"] = "list_field_usage"
    skip: int = Field(0, ge=0)
    top: int = Field(100, ge=1, le=10000)


class RunFormula(_Table):
    """Evaluate a Quickbase formula, optionally against a record."""
    operation: Literal["run_formula"] = "run_formula"
    formula: str = Field(..., min_length=1)
    record_id: int | None = Field(None, gt=0)


class RecordValue(_Input):
    value: Any = Field(..., description="The native Quickbase field value, including null to clear a field.")


class UpsertRecords(_Table):
    """Insert or update records; supply the key field to update existing rows."""
    operation: Literal["upsert_records"] = "upsert_records"
    data: Annotated[list[dict[Annotated[str, Field(pattern=r"^[0-9]+$")], RecordValue]], Field(min_length=1), BeforeValidator(_json_input, json_schema_input_type=str)] = Field(..., title="Records (JSON)", description='JSON array of records keyed by field ID, for example [{"6":{"value":"This is my text"}}].', json_schema_extra=JSON_EDITOR)
    merge_field_id: FieldId | None = None
    fields_to_return: JsonFieldIds | None = Field(None, title="Fields to return (JSON)", description="JSON array of field IDs, for example [6, 7].", json_schema_extra=JSON_EDITOR)


class DeleteRecords(_Table):
    """Delete only records matching the supplied query or record IDs."""
    operation: Literal["delete_records"] = "delete_records"
    where: RecordFilter = Field(..., description="Explicit Quickbase query filter or JSON array of record IDs, for example [1, 2, 3]. A matching-all filter deletes all records.")


class SortField(_Input):
    fieldId: FieldId
    order: Literal["ASC", "DESC", "equal-values"]


class QueryRecords(_Table):
    """Query one page of records using Quickbase filters and field IDs."""
    operation: Literal["query_records"] = "query_records"
    where: RecordFilter | None = Field(None, description="Quickbase query filter or JSON array of record IDs, for example [1, 2, 3].")
    select: JsonFieldIds | None = Field(None, title="Select fields (JSON)", description="JSON array of field IDs, for example [1, 2, 3].", json_schema_extra=JSON_EDITOR)
    sort_by: Annotated[list[SortField], BeforeValidator(_json_input, json_schema_input_type=str)] | None = Field(None, title="Sort by (JSON)", description='JSON array, for example [{"fieldId": 4, "order": "ASC"}].', json_schema_extra=JSON_EDITOR)
    skip: int = Field(0, ge=0)
    top: int = Field(100, ge=0, le=10000)


QuickbaseOperation = Annotated[Union[
    GetApp, CreateApp, UpdateApp, ListAppEvents, ListTables, CreateTable, GetTable,
    UpdateTable, ListReports, GetReport, RunReport, ListFields, GetField,
    CreateField, UpdateField, ListFieldUsage, RunFormula, UpsertRecords,
    DeleteRecords, QueryRecords,
], Field(discriminator="operation")]


class QuickbaseConfig(NodeConfig[QuickbaseOperation, QuickbaseUserTokenCredential]):
    pass


class QuickbaseNode(WorkflowNode):
    integration_type = "automation-quickbase"
    connection_evidence = ConnectionEvidence(noun="app", identity_operation="get_app")

    @classmethod
    def get_config_model(cls):
        return QuickbaseConfig

    def _request_parts(self):
        config = self.config.config
        op = config.operation
        app_id = getattr(config, "app_id", None) or self.config.credentials.app_id
        table_id = getattr(config, "table_id", None)
        method, path, params, body = "GET", "", {}, None
        if op in {"get_app", "update_app", "list_app_events"}:
            path = "/apps/" + quote(app_id, safe="") + ("/events" if op == "list_app_events" else "")
        elif op == "create_app":
            path = "/apps"
        elif op in {"list_tables", "create_table", "get_table", "update_table"}:
            path = "/tables" + ("/" + quote(table_id, safe="") if op in {"get_table", "update_table"} else "")
            params = {"appId": app_id}
        elif op in {"list_reports", "get_report", "run_report"}:
            path = "/reports" + ("/" + quote(config.report_id, safe="") if op != "list_reports" else "")
            params = {"tableId": table_id}
            if op == "run_report":
                method, path = "POST", path + "/run"
                params.update(skip=config.skip, top=config.top)
        elif op in {"list_fields", "get_field", "create_field", "update_field", "list_field_usage"}:
            path = "/fields" + ("/" + str(config.field_id) if op in {"get_field", "update_field"} else "")
            params = {"tableId": table_id}
            if op == "list_field_usage":
                path = "/fields/usage"
                params.update(skip=config.skip, top=config.top)
            elif op in {"list_fields", "get_field"}:
                params["includeFieldPerms"] = str(config.include_field_perms).lower()
        elif op == "run_formula":
            method, path = "POST", "/formula/run"
            body = {"from": table_id, "formula": config.formula}
            if config.record_id is not None:
                body["rid"] = config.record_id
        elif op == "upsert_records":
            method, path = "POST", "/records"
            body = {"to": table_id, "data": [ {key: value.model_dump() for key, value in row.items()} for row in config.data]}
            if config.merge_field_id is not None:
                body["mergeFieldId"] = config.merge_field_id
            if config.fields_to_return is not None:
                body["fieldsToReturn"] = config.fields_to_return
        elif op == "delete_records":
            method, path, body = "DELETE", "/records", {"from": table_id, "where": config.where}
        elif op == "query_records":
            method, path = "POST", "/records/query"
            body = {"from": table_id, "options": {"skip": config.skip, "top": config.top}}
            for source, target in (("where", "where"), ("select", "select"), ("sort_by", "sortBy")):
                value = getattr(config, source)
                if value is not None:
                    body[target] = [item.model_dump() for item in value] if source == "sort_by" else value
        else:
            raise ValueError("Unsupported Quickbase operation")

        if op in {"create_app", "update_app", "create_table", "update_table", "create_field", "update_field"}:
            method, body = "POST", {}
            for source, target in (("name", "name"), ("description", "description"), ("assign_token", "assignToken"),
                                   ("single_record_name", "singleRecordName"), ("plural_record_name", "pluralRecordName"),
                                   ("label", "label"), ("field_type", "fieldType"), ("field_help", "fieldHelp")):
                value = getattr(config, source, None)
                if value is not None:
                    body[target] = value
            if op.startswith("update_") and not body:
                raise ValueError("Provide at least one field to update")
        return method, path, params, body

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Quickbase user token")
        credential = self.config.credentials
        method, path, params, body = self._request_parts()
        headers = {"Authorization": "QB-USER-TOKEN " + credential.user_token,
                   "QB-Realm-Hostname": credential.realm_hostname, "Accept": "application/json",
                   "User-Agent": "NoClick-Quickbase/1.0"}
        kwargs = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.quickbase.com/v1" + path, **kwargs)
        if response.status_code >= 300:
            try:
                error = response.json()
                message = error.get("message", "Quickbase request failed")
                description = error.get("description")
            except (ValueError, AttributeError):
                message, description = "Quickbase returned a non-JSON error", None
            return {"status": "error", "success": False, "status_code": response.status_code,
                    "message": str(message).replace(credential.user_token, "[redacted]"),
                    "description": str(description).replace(credential.user_token, "[redacted]") if description else None}
        if len(response.content) > 20_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected bounded JSON from Quickbase")
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Unexpected Quickbase response shape")
        if isinstance(payload, dict) and "message" in payload and "description" in payload:
            return {"status": "error", "success": False, "message": str(payload["message"]).replace(credential.user_token, "[redacted]")}
        # Quickbase reports row-level upsert failures in metadata even on HTTP 200.
        failures = payload.get("metadata", {}).get("lineErrors") if isinstance(payload, dict) and isinstance(payload.get("metadata", {}), dict) else None
        output = {"status": "partial" if failures else "success", "success": not bool(failures),
                  "operation": self.config.config.operation, "data": payload}
        if self.config.config.operation in {"query_records", "run_report"}:
            metadata = payload.get("metadata") if isinstance(payload, dict) else None
            if not isinstance(metadata, dict) or any(type(metadata.get(key)) is not int or metadata[key] < 0 for key in ("numRecords", "totalRecords")):
                raise ValueError("Quickbase pagination metadata is missing or invalid")
            if "skip" in metadata and metadata["skip"] != self.config.config.skip:
                raise ValueError("Quickbase returned a different pagination offset")
            next_skip = self.config.config.skip + metadata["numRecords"]
            output["next_skip"] = next_skip if metadata["numRecords"] > 0 and next_skip < metadata["totalRecords"] else None
        # Do not allow an echoed token to escape in provider data or error details.
        output = json.loads(json.dumps(output).replace(json.dumps(credential.user_token)[1:-1], "[redacted]"))
        await self.emit(output)
        return output
