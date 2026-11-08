"""Fillout forms and Zite database operations with the unified REST API key.

Official references:
https://www.fillout.com/help/fillout-rest-api
https://developers.zite.com/api/overview
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, HttpUrl

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


_BASE_URLS = {
    "zite": ("https://api.zite.com/v1/api", "https://tables.zite.com/api/v1"),
    "fillout_us": ("https://api.fillout.com/v1/api", "https://tables.zite.com/api/v1"),
    "fillout_eu": ("https://eu-api.fillout.com/v1/api", "https://tables.zite.com/api/v1"),
}
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FilloutApiKeyCredential(BaseModel):
    """One key grants access to Forms and Database APIs in the chosen region."""

    credential_type: Literal["fillout_api_key"] = Field(
        "fillout_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", min_length=1,
        description="Generate this in Zite / Fillout → Settings → Developer → API key",
        json_schema_extra={"ui:widget": "password"},
    )
    api_region: Literal["zite", "fillout_us", "fillout_eu"] = Field(
        "zite", title="API Region",
        description="Choose the Forms API base URL shown in Developer settings",
    )

    model_config = ConfigDict(title="Fillout API Key", json_schema_extra={
        "x-credential-url": "https://app.zite.com/home/settings/developer",
        "x-credential-instructions": "Enable the REST API in Settings → Developer, then copy its API key. The same key works for forms and databases.",
    })


def _operation(name: str, category: str, title: str) -> Any:
    return Field(name, title=title, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": title, "x-is-trigger": False,
    })


def _picker(field_name: str, title: str, *, depends_on: Optional[str] = None) -> Any:
    options: Dict[str, Any] = {
        "field_name": field_name, "placeholder": f"Choose {title.lower()}",
        "searchable": True, "allow_custom": True,
        "custom_placeholder": f"Or enter {title.lower()} ID",
    }
    if depends_on:
        options["depends_on"] = depends_on
    return Field(..., title=title, json_schema_extra={"x-dynamic-options": options})


def _json_field(title: str, description: str, default: Any = ...) -> Any:
    return Field(default, title=title, description=description,
                 json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class _Form(BaseModel):
    form_id: str = _picker("form_id", "Form")


class _Database(BaseModel):
    database_id: str = _picker("database_id", "Database")


class _Table(_Database):
    table_id: str = _picker("table_id", "Table", depends_on="database_id")


class _Record(_Table):
    record_id: str = Field(..., title="Record ID")


# Forms and submissions
class ListForms(BaseModel):
    operation: Literal["list_forms"] = _operation("list_forms", "Forms", "List Forms")


class GetForm(_Form):
    operation: Literal["get_form"] = _operation("get_form", "Forms", "Get Form Metadata")


class ListSubmissions(_Form):
    operation: Literal["list_submissions"] = _operation("list_submissions", "Submissions", "List Submissions")
    limit: int = Field(50, ge=1, le=150, title="Limit")
    offset: int = Field(0, ge=0, title="Offset")
    after_date: Optional[str] = Field(None, title="After Date", description="ISO 8601 date-time")
    before_date: Optional[str] = Field(None, title="Before Date", description="ISO 8601 date-time")
    status: Optional[Literal["finished", "in_progress"]] = Field(None, title="Status")
    include_edit_link: bool = Field(False, title="Include Edit Link")
    include_preview: bool = Field(False, title="Include Preview Responses")
    sort: Literal["asc", "desc"] = Field("asc", title="Sort")
    search: Optional[str] = Field(None, title="Search")


class GetSubmission(_Form):
    operation: Literal["get_submission"] = _operation("get_submission", "Submissions", "Get Submission")
    submission_id: str = Field(..., title="Submission ID")
    include_edit_link: bool = Field(False, title="Include Edit Link")


class CreateSubmissions(_Form):
    operation: Literal["create_submissions"] = _operation("create_submissions", "Submissions", "Create Submissions")
    submissions_json: str = _json_field(
        "Submissions JSON", "JSON array of up to 10 submissions. Each has a questions array with question id and value."
    )


class DeleteSubmission(_Form):
    operation: Literal["delete_submission"] = _operation("delete_submission", "Submissions", "Delete Submission")
    submission_id: str = Field(..., title="Submission ID")


class CreateFormWebhook(_Form):
    operation: Literal["create_form_webhook"] = _operation("create_form_webhook", "Form Webhooks", "Create Form Webhook")
    url: HttpUrl = Field(..., title="Webhook URL", description="HTTPS endpoint that will receive form submissions")


class DeleteFormWebhook(BaseModel):
    operation: Literal["delete_form_webhook"] = _operation("delete_form_webhook", "Form Webhooks", "Remove Form Webhook")
    webhook_id: str = Field(..., title="Webhook ID")


# Databases and schema
class ListDatabases(BaseModel):
    operation: Literal["list_databases"] = _operation("list_databases", "Databases", "List Databases")


class GetDatabase(_Database):
    operation: Literal["get_database"] = _operation("get_database", "Databases", "Get Database")


class CreateDatabase(BaseModel):
    operation: Literal["create_database"] = _operation("create_database", "Databases", "Create Database")
    name: str = Field(..., min_length=1, title="Database Name")
    tables_json: str = _json_field(
        "Tables JSON", "JSON array of tables. Each table needs a name and fields; each field needs name, type, and template.",
        '[{"name":"Entries","fields":[{"name":"Name","type":"single_line_text","template":{}}]}]',
    )


class DeleteDatabase(_Database):
    operation: Literal["delete_database"] = _operation("delete_database", "Databases", "Delete Database")


class CreateTable(_Database):
    operation: Literal["create_table"] = _operation("create_table", "Tables", "Create Table")
    name: str = Field(..., min_length=1, title="Table Name")
    fields_json: str = _json_field(
        "Fields JSON", "JSON array of fields, each with name, type, and template.",
        '[{"name":"Name","type":"single_line_text","template":{}}]',
    )


class UpdateTable(_Table):
    operation: Literal["update_table"] = _operation("update_table", "Tables", "Rename Table")
    name: str = Field(..., min_length=1, title="New Name")


class DeleteTable(_Table):
    operation: Literal["delete_table"] = _operation("delete_table", "Tables", "Delete Table")


class ListFields(_Table):
    operation: Literal["list_fields"] = _operation("list_fields", "Fields", "List Fields")


class CreateField(_Table):
    operation: Literal["create_field"] = _operation("create_field", "Fields", "Create Field")
    name: str = Field(..., min_length=1, title="Field Name")
    field_type: str = Field("single_line_text", title="Field Type", description="Zite field type, such as single_line_text, email, number, or date")
    template_json: str = _json_field("Template JSON", "Field-specific configuration object", "{}")


class UpdateField(_Table):
    operation: Literal["update_field"] = _operation("update_field", "Fields", "Update Field")
    field_id: str = _picker("field_id", "Field", depends_on="table_id")
    name: Optional[str] = Field(None, title="New Name")
    template_json: Optional[str] = _json_field("Template JSON", "Optional field-specific configuration object", None)


class DeleteField(_Table):
    operation: Literal["delete_field"] = _operation("delete_field", "Fields", "Delete Field")
    field_id: str = _picker("field_id", "Field", depends_on="table_id")


# Records
class ListRecords(_Table):
    operation: Literal["list_records"] = _operation("list_records", "Records", "List Records")
    limit: int = Field(100, ge=1, le=2000, title="Limit")
    offset: int = Field(0, ge=0, title="Offset")
    filter_json: Optional[str] = _json_field("Filter JSON", "Optional Zite filter object", None)
    sort_json: Optional[str] = _json_field("Sort JSON", "Optional array of Zite sort objects", None)


class GetRecord(_Record):
    operation: Literal["get_record"] = _operation("get_record", "Records", "Get Record")


class CreateRecord(_Table):
    operation: Literal["create_record"] = _operation("create_record", "Records", "Create Record")
    record_json: str = _json_field("Record JSON", "Object of field names or IDs to values, such as {\"Name\":\"Example\"}")


class UpdateRecord(_Record):
    operation: Literal["update_record"] = _operation("update_record", "Records", "Update Record")
    record_json: str = _json_field("Record JSON", "Object of field names or IDs to values")


class DeleteRecord(_Record):
    operation: Literal["delete_record"] = _operation("delete_record", "Records", "Delete Record")


# Database webhooks
class ListDatabaseWebhooks(_Database):
    operation: Literal["list_database_webhooks"] = _operation("list_database_webhooks", "Database Webhooks", "List Database Webhooks")


class CreateDatabaseWebhook(_Database):
    operation: Literal["create_database_webhook"] = _operation("create_database_webhook", "Database Webhooks", "Create Database Webhook")
    url: HttpUrl = Field(..., title="Webhook URL")
    events_json: str = _json_field("Events JSON", "Array of record, table, or field events", '["record.created"]')
    table_id: Optional[str] = Field(None, title="Table ID", description="Leave blank for all tables")


class DeleteDatabaseWebhook(_Database):
    operation: Literal["delete_database_webhook"] = _operation("delete_database_webhook", "Database Webhooks", "Delete Database Webhook")
    webhook_id: str = Field(..., title="Webhook ID")


FilloutOperation = Annotated[
    Union[
        ListForms, GetForm, ListSubmissions, GetSubmission, CreateSubmissions,
        DeleteSubmission, CreateFormWebhook, DeleteFormWebhook,
        ListDatabases, GetDatabase, CreateDatabase, DeleteDatabase,
        CreateTable, UpdateTable, DeleteTable, ListFields, CreateField,
        UpdateField, DeleteField, ListRecords, GetRecord, CreateRecord,
        UpdateRecord, DeleteRecord, ListDatabaseWebhooks,
        CreateDatabaseWebhook, DeleteDatabaseWebhook,
    ],
    Discriminator("operation"),
]


class FilloutNodeConfig(NodeConfig[FilloutOperation, FilloutApiKeyCredential]):
    pass


def _id(value: str) -> str:
    return quote(str(value), safe="")


def _json_value(raw: str, title: str, expected: type) -> Any:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{title} must be valid JSON") from exc
    if not isinstance(value, expected):
        raise ValueError(f"{title} must be a JSON {'array' if expected is list else 'object'}")
    return value


async def _request(
    credentials: FilloutApiKeyCredential, api: Literal["forms", "database"],
    method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Any:
    base = _BASE_URLS[credentials.api_region][0 if api == "forms" else 1]
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        response = await client.request(
            method, f"{base}{path}",
            headers={"Authorization": f"Bearer {credentials.api_key}", "Accept": "application/json"},
            params={k: v for k, v in (params or {}).items() if v is not None},
            json=body,
        )
    if not response.is_success:
        code = ""
        try:
            error = response.json().get("error", {})
            candidate = error.get("code", "") if isinstance(error, dict) else ""
            if isinstance(candidate, str) and _CODE_RE.fullmatch(candidate):
                code = f" ({candidate})"
        except (ValueError, AttributeError):
            pass
        raise ValueError(f"Fillout {api} API returned HTTP {response.status_code}{code}")
    if response.status_code == 204 or not response.content:
        return {"success": True}
    try:
        result = response.json()
    except ValueError as exc:
        raise ValueError(f"Fillout {api} API returned an invalid JSON response") from exc
    if isinstance(result, dict) and (result.get("error") or result.get("success") is False):
        raise ValueError(f"Fillout {api} API returned an error")
    return result


class FilloutNode(WorkflowNode):
    """Read and write Fillout forms, submissions, and Zite database data."""

    integration_type = "automation-fillout"

    edit_examples = [
        "List my Fillout forms and their submissions",
        "Save a new record in my Zite database",
        "Update a database record after a form response",
        "Find submissions from this week",
    ]
    connection_evidence = ConnectionEvidence(field="form_id", noun="forms", operation="list_forms")

    @classmethod
    def get_config_model(cls):
        return FilloutNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not credential_data or not credential_data.get("api_key"):
            return {"options": [], "next_page_token": None}
        credentials = FilloutApiKeyCredential.model_validate(credential_data)
        ctx = context or {}
        items = []
        label_key = "name"
        if field_name == "form_id":
            items = await _request(credentials, "forms", "GET", "/forms")
            id_key = "formId"
        elif field_name == "database_id":
            items = await _request(credentials, "database", "GET", "/bases")
            id_key = "id"
        elif field_name == "table_id" and ctx.get("database_id"):
            database = await _request(credentials, "database", "GET", f"/bases/{_id(ctx['database_id'])}")
            items = database.get("tables", [])
            id_key = "id"
        elif field_name == "field_id" and ctx.get("database_id") and ctx.get("table_id"):
            fields = await _request(credentials, "database", "GET", f"/bases/{_id(ctx['database_id'])}/tables/{_id(ctx['table_id'])}/fields")
            items = fields if isinstance(fields, list) else fields.get("fields", [])
            id_key = "id"
        else:
            return {"options": [], "next_page_token": None}
        if not isinstance(items, list):
            raise ValueError("Fillout returned an unexpected options response")
        options = [
            {"value": str(item[id_key]), "label": str(item.get(label_key) or item[id_key])}
            for item in items if isinstance(item, dict) and item.get(id_key)
            and (not search or search.casefold() in str(item.get(label_key) or item[id_key]).casefold())
        ]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, FilloutNodeConfig) or not self.config.credentials:
            raise ValueError("Fillout credentials and configuration are required")
        config = self.config.config
        credentials = self.config.credentials
        op = config.operation
        started = time.monotonic()
        forms = "forms"
        database = "database"
        form_path = f"/forms/{_id(config.form_id)}" if hasattr(config, "form_id") else ""
        db_path = f"/bases/{_id(config.database_id)}" if hasattr(config, "database_id") else ""
        table_path = f"{db_path}/tables/{_id(config.table_id)}" if hasattr(config, "table_id") else ""

        if op == "list_forms":
            result = await _request(credentials, forms, "GET", "/forms")
        elif op == "get_form":
            result = await _request(credentials, forms, "GET", form_path)
        elif op == "list_submissions":
            params = {"limit": config.limit, "offset": config.offset, "afterDate": config.after_date,
                      "beforeDate": config.before_date, "status": config.status,
                      "includeEditLink": config.include_edit_link, "includePreview": config.include_preview,
                      "sort": config.sort, "search": config.search}
            result = await _request(credentials, forms, "GET", f"{form_path}/submissions", params=params)
        elif op == "get_submission":
            result = await _request(credentials, forms, "GET", f"{form_path}/submissions/{_id(config.submission_id)}",
                                    params={"includeEditLink": config.include_edit_link})
        elif op == "create_submissions":
            submissions = _json_value(config.submissions_json, "Submissions", list)
            if not 1 <= len(submissions) <= 10 or any(not isinstance(s, dict) or not isinstance(s.get("questions"), list) for s in submissions):
                raise ValueError("Submissions must contain 1–10 objects with questions arrays")
            result = await _request(credentials, forms, "POST", f"{form_path}/submissions", body={"submissions": submissions})
        elif op == "delete_submission":
            result = await _request(credentials, forms, "DELETE", f"{form_path}/submissions/{_id(config.submission_id)}")
        elif op == "create_form_webhook":
            result = await _request(credentials, forms, "POST", "/webhook/create",
                                    body={"formId": config.form_id, "url": str(config.url)})
        elif op == "delete_form_webhook":
            result = await _request(credentials, forms, "POST", "/webhook/delete", body={"webhookId": config.webhook_id})
        elif op == "list_databases":
            result = await _request(credentials, database, "GET", "/bases")
        elif op == "get_database":
            result = await _request(credentials, database, "GET", db_path)
        elif op == "create_database":
            tables = _json_value(config.tables_json, "Tables", list)
            if not tables:
                raise ValueError("Tables must contain at least one table")
            result = await _request(credentials, database, "POST", "/bases", body={"name": config.name, "tables": tables})
        elif op == "delete_database":
            result = await _request(credentials, database, "DELETE", db_path)
        elif op == "create_table":
            fields = _json_value(config.fields_json, "Fields", list)
            if not fields:
                raise ValueError("Fields must contain at least one field")
            result = await _request(credentials, database, "POST", f"{db_path}/tables", body={"name": config.name, "fields": fields})
        elif op == "update_table":
            result = await _request(credentials, database, "PATCH", table_path, body={"name": config.name})
        elif op == "delete_table":
            result = await _request(credentials, database, "DELETE", table_path)
        elif op == "list_fields":
            result = await _request(credentials, database, "GET", f"{table_path}/fields")
        elif op == "create_field":
            template = _json_value(config.template_json, "Template", dict)
            result = await _request(credentials, database, "POST", f"{table_path}/fields",
                                    body={"name": config.name, "type": config.field_type, "template": template})
        elif op == "update_field":
            body = {"name": config.name} if config.name is not None else {}
            if config.template_json is not None:
                body["template"] = _json_value(config.template_json, "Template", dict)
            if not body:
                raise ValueError("Provide a field name or template to update")
            result = await _request(credentials, database, "PATCH", f"{table_path}/fields/{_id(config.field_id)}", body=body)
        elif op == "delete_field":
            result = await _request(credentials, database, "DELETE", f"{table_path}/fields/{_id(config.field_id)}")
        elif op == "list_records":
            body: Dict[str, Any] = {"limit": config.limit, "offset": config.offset}
            if config.filter_json:
                body["filter"] = _json_value(config.filter_json, "Filter", dict)
            if config.sort_json:
                body["sort"] = _json_value(config.sort_json, "Sort", list)
            result = await _request(credentials, database, "POST", f"{table_path}/records/list", body=body)
        elif op == "get_record":
            result = await _request(credentials, database, "GET", f"{table_path}/records/{_id(config.record_id)}")
        elif op == "create_record":
            result = await _request(credentials, database, "POST", f"{table_path}/records",
                                    body={"record": _json_value(config.record_json, "Record", dict)})
        elif op == "update_record":
            result = await _request(credentials, database, "PATCH", f"{table_path}/records/{_id(config.record_id)}",
                                    body={"record": _json_value(config.record_json, "Record", dict)})
        elif op == "delete_record":
            result = await _request(credentials, database, "DELETE", f"{table_path}/records/{_id(config.record_id)}")
        elif op == "list_database_webhooks":
            result = await _request(credentials, database, "GET", f"{db_path}/webhooks")
        elif op == "create_database_webhook":
            events = _json_value(config.events_json, "Events", list)
            if not events or any(not isinstance(event, str) for event in events):
                raise ValueError("Events must be a non-empty array of event names")
            body = {"url": str(config.url), "events": events}
            if config.table_id:
                body["tableId"] = config.table_id
            result = await _request(credentials, database, "POST", f"{db_path}/webhooks", body=body)
        elif op == "delete_database_webhook":
            result = await _request(credentials, database, "DELETE", f"{db_path}/webhooks/{_id(config.webhook_id)}")
        else:
            raise ValueError(f"Unsupported Fillout operation: {op}")

        return {"status": "success", "action": op, "data": result,
                "timing_ms": {"request": round((time.monotonic() - started) * 1000, 2)}}
