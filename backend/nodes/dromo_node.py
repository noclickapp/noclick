"""Dromo v1 saved schemas, embedded uploads and JSON headless imports.

Contract: https://developer.dromo.io/api-reference/openapi.json (version 1.0).
Each operation sends one request; result URLs are returned without following them.
"""
from __future__ import annotations

import json
from typing import Annotated, ClassVar, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.dromo.io/api/v1"
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class DromoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dromo Backend API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.dromo.io/",
        "x-credential-instructions": "Paste the Backend license key from your Dromo dashboard, not the frontend license key. NoClick sends it to app.dromo.io as X-Dromo-License-Key. Connecting lists your saved schemas. Headless imports require the Enterprise Headless add-on and may consume your plan allowance. Download URLs expire; treat them as secrets."})
    credential_type: Literal["dromo_api_key"] = Field("dromo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Backend license key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Backend license key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the backend license key, without a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class WireInput(Input):
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def supplied_nulls(self):
        if any(getattr(self, key) is None and key not in self.nullable_fields for key in self.model_fields_set):
            raise ValueError("Omit optional fields instead of sending null where the Dromo contract disallows it")
        return self


class SchemaField(WireInput):
    key: str
    type: str | list
    label: str
    description: str | None = None
    alternateMatches: list[str] | None = None
    validators: list[dict] | None = None
    invalidValueMessage: str | None = None
    readOnly: bool | None = None
    hidden: bool | None = None
    requireMapping: bool | None = None
    manyToOne: bool | None = None


class SchemaSettings(WireInput):
    nullable_fields = frozenset({"maxRecords", "webhookUrl", "needsReviewWebhookUrl", "initialData"})
    importIdentifier: str | None = None
    title: str | None = None
    allowInvalidSubmit: bool | None = None
    invalidDataBehavior: Literal["BLOCK_SUBMIT", "INCLUDE_INVALID_ROWS", "REMOVE_INVALID_ROWS", "INCLUDE_INVALID_ROWS_AND_VALUES"] | None = None
    backendSync: bool | None = None
    backendSyncMode: Literal["DISABLED", "FULL_DATA", "MAPPINGS_ONLY"] | None = None
    manualInputDisabled: bool | None = None
    manualInputOnly: bool | None = None
    allowCustomFields: bool | None = None
    passThroughUnmappedColumns: bool | None = None
    maxRecords: int | None = None
    developmentMode: bool | None = None
    displayEncoding: bool | None = None
    styleOverrides: dict | None = None
    maxFileSize: int | None = None
    webhookUrl: str | None = None
    needsReviewWebhookUrl: str | None = None
    initialData: list | None = None


class ColumnHook(WireInput):
    fieldName: str
    callback: str


class StepHook(WireInput):
    type: Literal["UPLOAD_STEP", "REVIEW_STEP", "REVIEW_STEP_POST_HOOKS"]
    callback: str


class SchemaHooks(WireInput):
    rowHooks: list[str] | None = None
    bulkRowHooks: list[str] | None = None
    rowDeleteHooks: list[str] | None = None
    beforeFinishCallback: str | None = None
    columnHooks: list[ColumnHook] | None = None
    stepHooks: list[StepHook] | None = None


def _json(value, model):
    try:
        return TypeAdapter(model).validate_json(value, strict=True)
    except Exception:
        raise ValueError("Use valid JSON with the fields supported by the Dromo v1 API contract") from None


def _dump(value):
    return TypeAdapter(type(value)).dump_python(value, mode="json", exclude_unset=True)


class ListSchemas(Input):
    """List your organization's saved import schemas."""
    operation: Literal["list_schemas"] = "list_schemas"


class Resource(Input):
    id: str = Field(..., pattern=UUID_PATTERN, description="Dromo resource UUID.")


class GetSchema(Resource):
    """Get a saved import schema by UUID."""
    operation: Literal["get_schema"] = "get_schema"


class DeleteSchema(Resource):
    """Permanently delete a saved import schema."""
    operation: Literal["delete_schema"] = "delete_schema"


class SchemaWrite(Input):
    name: str = Field(..., min_length=1, description="Unique schema name within your organization.")
    fields_json: str = Field(..., description='JSON array of field objects, e.g. [{"key":"first_name","type":"string","label":"First Name","validators":[]}].', json_schema_extra={"ui:widget": "code_editor"})
    settings_json: str = Field("{}", description='JSON settings object, e.g. {"developmentMode":true}. PUT replaces the whole schema; supply all fields and settings you want to retain.', json_schema_extra={"ui:widget": "code_editor"})
    hooks_json: str | None = Field(None, description="Optional JSON hooks object containing serialized JavaScript callbacks.", json_schema_extra={"ui:widget": "code_editor"})

    @field_validator("fields_json")
    @classmethod
    def fields(cls, value):
        _json(value, list[SchemaField])
        return value

    @field_validator("settings_json")
    @classmethod
    def settings(cls, value):
        _json(value, SchemaSettings)
        return value

    @field_validator("hooks_json")
    @classmethod
    def hooks(cls, value):
        if value is not None:
            _json(value, SchemaHooks)
        return value


class CreateSchema(SchemaWrite):
    """Create a reusable saved import schema."""
    operation: Literal["create_schema"] = "create_schema"


class UpdateSchema(SchemaWrite, Resource):
    """Replace an existing saved schema with the supplied definition."""
    operation: Literal["update_schema"] = "update_schema"


class ListUploads(Input):
    """List one bounded range of embedded uploads; use end as the next start."""
    operation: Literal["list_uploads"] = "list_uploads"
    start: int = Field(0, ge=0)
    end: int = Field(100, ge=1, description="Exclusive range end; request at most 10000 uploads.")

    @model_validator(mode="after")
    def page(self):
        if not self.start < self.end <= self.start + 10000:
            raise ValueError("Use start < end and a range of at most 10000 uploads")
        return self


class GetUploadMetadata(Resource):
    """Read metadata and raw-file download URL for an embedded upload."""
    operation: Literal["get_upload_metadata"] = "get_upload_metadata"


class DeleteUpload(Resource):
    """Permanently delete an embedded upload."""
    operation: Literal["delete_upload"] = "delete_upload"


class GetUploadUrl(Resource):
    """Get an expiring signed URL for embedded upload result data."""
    operation: Literal["get_upload_url"] = "get_upload_url"


class ListHeadlessImports(Input):
    """List one page of headless imports, preserving pagination metadata."""
    operation: Literal["list_headless_imports"] = "list_headless_imports"
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=1000)


class GetHeadlessImport(Resource):
    """Read headless import status, review URL and errors without polling."""
    operation: Literal["get_headless_import"] = "get_headless_import"


class DeleteHeadlessImport(Resource):
    """Permanently delete a headless import."""
    operation: Literal["delete_headless_import"] = "delete_headless_import"


class GetHeadlessImportUrl(Resource):
    """Get an expiring signed URL for completed headless import result data."""
    operation: Literal["get_headless_import_url"] = "get_headless_import_url"


class CreateHeadlessImport(Input):
    """Start a JSON headless import; this returns a job, not completed results."""
    operation: Literal["create_headless_import"] = "create_headless_import"
    schema_id: str | None = Field(None, pattern=UUID_PATTERN, description="Saved schema UUID; supply this or inline fields, exclusively.")
    fields_json: str | None = Field(None, description=SchemaWrite.model_fields["fields_json"].description, json_schema_extra={"ui:widget": "code_editor"})
    settings_json: str | None = Field(None, description="Optional JSON settings override for this import only.", json_schema_extra={"ui:widget": "code_editor"})
    hooks_json: str | None = Field(None, description=SchemaWrite.model_fields["hooks_json"].description, json_schema_extra={"ui:widget": "code_editor"})
    initial_data_json: str = Field(..., max_length=15_000_000, description='Complete JSON data array, at most 15 MB. Example: [{"first_name":"Zeph","last_name":"paul.zeph@gmail.com"}].', json_schema_extra={"ui:widget": "code_editor"})

    @model_validator(mode="after")
    def body(self):
        if (self.schema_id is not None) == (self.fields_json is not None):
            raise ValueError("Supply exactly one of schema_id or fields_json")
        if self.fields_json is not None:
            SchemaWrite.fields(self.fields_json)
        if self.settings_json is not None:
            SchemaWrite.settings(self.settings_json)
        SchemaWrite.hooks(self.hooks_json)
        _json(self.initial_data_json, list)
        if len(self.initial_data_json.encode("utf-8")) > 15_000_000:
            raise ValueError("JSON data exceeds Dromo's 15 MB limit")
        return self


Operation = Annotated[Union[ListSchemas, GetSchema, CreateSchema, UpdateSchema, DeleteSchema,
    ListUploads, GetUploadMetadata, DeleteUpload, GetUploadUrl, ListHeadlessImports,
    GetHeadlessImport, CreateHeadlessImport, DeleteHeadlessImport, GetHeadlessImportUrl], Field(discriminator="operation")]


class DromoConfig(NodeConfig[Operation, DromoAPIKeyCredential]):
    pass


ROUTES = {
    "list_schemas": ("GET", "/schemas/"),
    "get_schema": ("GET", "/schemas/{id}/"),
    "create_schema": ("POST", "/schemas/"),
    "update_schema": ("PUT", "/schemas/{id}/"),
    "delete_schema": ("DELETE", "/schemas/{id}/"),
    "list_uploads": ("GET", "/uploads/"),
    "get_upload_metadata": ("GET", "/upload/{id}/metadata/"),
    "delete_upload": ("POST", "/upload/{id}/delete/"),
    "get_upload_url": ("GET", "/upload/{id}/url/"),
    "list_headless_imports": ("GET", "/headless/imports/"),
    "get_headless_import": ("GET", "/headless/imports/{id}/"),
    "create_headless_import": ("POST", "/headless/imports/"),
    "delete_headless_import": ("DELETE", "/headless/imports/{id}/"),
    "get_headless_import_url": ("GET", "/headless/imports/{id}/url/"),
}


def request_parts(op):
    method, path = ROUTES[op.operation]
    if "{id}" in path:
        path = path.replace("{id}", quote(op.id, safe=""))
    params, body = {}, None
    if isinstance(op, ListUploads):
        params = {"start": op.start, "end": op.end}
    elif isinstance(op, ListHeadlessImports):
        params = {"offset": op.offset, "limit": op.limit}
    elif isinstance(op, SchemaWrite):
        body = {"name": op.name, "fields": [_dump(v) for v in _json(op.fields_json, list[SchemaField])],
                "settings": _dump(_json(op.settings_json, SchemaSettings))}
        if op.hooks_json is not None:
            body["hooks"] = _dump(_json(op.hooks_json, SchemaHooks))
    elif isinstance(op, CreateHeadlessImport):
        body = {"initial_data": _json(op.initial_data_json, list)}
        if op.schema_id is not None:
            body["schema_id"] = op.schema_id
        if op.fields_json is not None:
            body["fields"] = [_dump(v) for v in _json(op.fields_json, list[SchemaField])]
        for name, model in (("settings", SchemaSettings), ("hooks", SchemaHooks)):
            value = getattr(op, name + "_json")
            if value is not None:
                body[name] = _dump(_json(value, model))
    return method, path, params, body


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class DromoNode(WorkflowNode):
    integration_type = "automation-dromo"
    connection_evidence = ConnectionEvidence(operation="list_schemas", noun="saved import schemas")

    @classmethod
    def get_config_model(cls):
        return DromoConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Dromo backend license key")
        op = self.config.config
        method, path, params, body = request_parts(op)
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params or None, json=body,
                headers={"X-Dromo-License-Key": token, "Accept": "application/json"})
        if response.is_error:
            output = {"status": "error", "http_status": response.status_code,
                      "message": _redact(response.text[:10000], token)}
        else:
            expected = 201 if op.operation in {"create_schema", "create_headless_import"} else 204 if method == "DELETE" else 200
            if response.status_code != expected:
                raise ValueError("Dromo returned an unexpected HTTP status")
            if method == "DELETE" or isinstance(op, DeleteUpload):
                payload = {"id": op.id, "deletion_acknowledged": True}
            else:
                if len(response.content) > 20_000_000:
                    raise ValueError("Dromo response exceeds the 20 MB bound")
                try:
                    payload = response.json()
                except (ValueError, UnicodeError):
                    raise ValueError("Dromo returned invalid JSON") from None
                if not isinstance(payload, list if isinstance(op, ListSchemas) else dict):
                    raise ValueError("Dromo returned an unexpected response shape")
                if isinstance(payload, dict) and ("error" in payload or "detail" in payload):
                    output = {"status": "error", "http_status": response.status_code, "message": _redact(json.dumps(payload), token)}
                    await self.emit(output)
                    return output
                if isinstance(op, ListSchemas) and any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in payload):
                    raise ValueError("Dromo did not return saved schema records")
                if isinstance(op, ListUploads) and not isinstance(payload.get("data"), list):
                    raise ValueError("Dromo did not return an upload page")
                if isinstance(op, ListHeadlessImports) and not isinstance(payload.get("results"), list):
                    raise ValueError("Dromo did not return a headless import page")
                if isinstance(op, (GetUploadUrl, GetHeadlessImportUrl)) and not isinstance(payload.get("presigned_url"), str):
                    raise ValueError("Dromo did not return a download URL")
                if isinstance(op, (GetSchema, CreateSchema, UpdateSchema)) and not isinstance(payload.get("name"), str):
                    raise ValueError("Dromo did not return a schema")
                if isinstance(op, (GetHeadlessImport, CreateHeadlessImport, GetUploadMetadata)) and not isinstance(payload.get("id"), str):
                    raise ValueError("Dromo did not return an import ID")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": _redact(payload, token)}
        await self.emit(output)
        return output
