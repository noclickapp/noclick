"""Glide API v2 Big Tables, row mutations, asynchronous jobs and data stashes."""
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

BASE_URL = "https://api.glideapps.com"
AUTH_DOCS = "https://apidocs.glideapps.com/api-reference/v2/general/authentication"
ROW_SCHEMA = {"type": "object", "additionalProperties": {}}
ROWS_SCHEMA = {"type": "array", "items": ROW_SCHEMA}


def _json_field(schema):
    return {"ui:widget": "code_editor", "x-code-language": "json",
            "contentMediaType": "application/json", "contentSchema": schema}


def _json(value, kind):
    try:
        parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError("Enter valid JSON") from None
    if not isinstance(parsed, kind) or (kind is list and any(not isinstance(row, dict) for row in parsed)):
        raise ValueError("Use a JSON object" if kind is dict else "Use a JSON array of row objects")
    return parsed


class GlideAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Glide API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Copy your API auth token from the Glide Data Editor. It belongs to your Glide user and team and grants access to that team's applications and data. Paste the token without the Bearer prefix."})
    credential_type: Literal["glide_apps_api_token"] = Field("glide_apps_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token", repr=False,
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListTables(_Input):
    """List all Big Tables in the token's team."""
    operation: Literal["list_tables"] = "list_tables"


class _Table(_Input):
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$", title="Table ID")


class ListRows(_Table):
    """Read one page; pass the returned continuation to read the next page."""
    operation: Literal["list_rows"] = "list_rows"
    limit: int = Field(100, ge=1, le=1000)
    continuation: str | None = Field(None, max_length=8192)


class _Row(_Table):
    row_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$", title="Row ID")


class GetRow(_Row):
    operation: Literal["get_row"] = "get_row"


class _Rows(_Input):
    rows_json: str = Field(..., max_length=5_000_000, title="Rows JSON",
        description="Array of row objects keyed by Glide column IDs. Empty arrays are allowed.",
        json_schema_extra=_json_field(ROWS_SCHEMA))

    @field_validator("rows_json")
    @classmethod
    def rows(cls, value):
        _json(value, list)
        return value


class _SchemaPolicy(_Input):
    on_schema_error: Literal["abort", "dropColumns", "updateSchema"] = Field("abort",
        description="How Glide handles data that differs from the table schema.")


ColumnType = Literal["string", "uri", "imageURI", "audioURI", "markdown", "phoneNumber", "emailAddress",
                     "emoji", "date", "time", "dateTime", "duration", "number", "boolean", "json"]


class Column(_Input):
    id: str
    displayName: str | None = None
    type: ColumnType


class _Columns(_Input):
    columns: list[Column] | None = Field(None, description="Optional column schema; omit to infer from rows.")


class CreateTable(_Rows, _SchemaPolicy, _Columns):
    """Create a Big Table with initial rows and optional explicit column types."""
    operation: Literal["create_table"] = "create_table"
    name: str = Field(..., min_length=1, max_length=1024)
    apps_to_link: list[str] | None = Field(None, title="App IDs to Link")
    asynchronous: bool = Field(False, description="Request a job instead of waiting for completion.")


class ImportTable(_SchemaPolicy):
    """Ask Glide to import a publicly accessible dataset URL as a new Big Table."""
    operation: Literal["import_table"] = "import_table"
    from_url: str = Field(..., json_schema_extra={"format": "uri"}, pattern=r"^https://[^\s]+$", max_length=8192)
    display_name: str | None = None
    apps_to_link: list[str] | None = None


class _Version(_Input):
    if_match: str | None = Field(None, pattern=r'^"[0-9]+"$',
        description='Optional quoted version from Glide etag, for example "123". A stale version returns 412.')


class ReplaceTable(_Table, _Rows, _SchemaPolicy, _Columns, _Version):
    """Replace all table rows. Existing data is overwritten, including with an empty array."""
    operation: Literal["replace_table"] = "replace_table"
    asynchronous: bool = False


class AddRows(_Table, _Rows, _SchemaPolicy):
    operation: Literal["add_rows"] = "add_rows"


class UpdateRow(_Row, _SchemaPolicy, _Version):
    operation: Literal["update_row"] = "update_row"
    values_json: str = Field(..., max_length=1_000_000, title="Column Values JSON",
        description="Object of column IDs and new values; omitted columns are unchanged.",
        json_schema_extra=_json_field(ROW_SCHEMA))

    @field_validator("values_json")
    @classmethod
    def values(cls, value):
        _json(value, dict)
        return value


class DeleteRow(_Row):
    operation: Literal["delete_row"] = "delete_row"


class GetJob(_Input):
    operation: Literal["get_job"] = "get_job"
    job_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")


class _Stash(_Input):
    stash_id: str = Field(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,255}$")


class SetStashChunk(_Stash, _Rows):
    """Set one stash chunk. Reusing its serial overwrites that chunk."""
    operation: Literal["set_stash_chunk"] = "set_stash_chunk"
    serial: str = Field(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,255}$")


class DeleteStash(_Stash):
    operation: Literal["delete_stash"] = "delete_stash"


GlideConfig = Annotated[Union[ListTables, ListRows, GetRow, CreateTable, ImportTable, ReplaceTable,
    AddRows, UpdateRow, DeleteRow, GetJob, SetStashChunk, DeleteStash], Field(discriminator="operation")]


class GlideNodeConfig(NodeConfig[GlideConfig, GlideAPITokenCredential]):
    pass


def _request_parts(op):
    action = op.operation
    method, path, params, headers, body = "GET", "/tables", {}, {}, None
    if isinstance(op, _Table):
        path += "/" + quote(op.table_id, safe="")
        if action != "replace_table":
            path += "/rows"
        if isinstance(op, _Row):
            path += "/" + quote(op.row_id, safe="")
    if isinstance(op, _SchemaPolicy):
        params["onSchemaError"] = op.on_schema_error
    if isinstance(op, _Version) and op.if_match is not None:
        headers["if-match"] = op.if_match
    if action == "list_rows":
        params["limit"] = op.limit
        if op.continuation is not None:
            params["continuation"] = op.continuation
    elif action in {"create_table", "replace_table"}:
        method = "POST" if action == "create_table" else "PUT"
        headers["x-glide-asynchronous"] = str(op.asynchronous).lower()
        body = {"rows": _json(op.rows_json, list)}
        if op.columns is not None:
            body["schema"] = {"columns": [col.model_dump(exclude_none=True) for col in op.columns]}
        if action == "create_table":
            body["name"] = op.name
            if op.apps_to_link is not None:
                body["appsToLink"] = op.apps_to_link
    elif action == "import_table":
        method, path = "POST", "/tables/import"
        body = {"fromUrl": op.from_url}
        if op.display_name is not None:
            body["displayName"] = op.display_name
        if op.apps_to_link is not None:
            body["appsToLink"] = op.apps_to_link
    elif action == "add_rows":
        method, body = "POST", _json(op.rows_json, list)
    elif action == "update_row":
        method, body = "PATCH", _json(op.values_json, dict)
    elif action == "delete_row":
        method = "DELETE"
    elif action == "get_job":
        path = "/jobs/" + quote(op.job_id, safe="")
    elif isinstance(op, _Stash):
        path = "/stashes/" + quote(op.stash_id, safe="")
        if action == "set_stash_chunk":
            method, body = "PUT", _json(op.rows_json, list)
            path += "/" + quote(op.serial, safe="")
        else:
            method = "DELETE"
    return method, path, params, headers, body


def _response(op, code, payload):
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("Glide returned an unexpected response")
    action = op.operation
    data = payload.get("data")
    if action in {"update_row", "delete_row", "set_stash_chunk", "delete_stash"}:
        if code != 200 or payload != {}:
            raise ValueError("Glide mutation acknowledgement is invalid")
    elif action in {"list_tables", "list_rows", "import_table"}:
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("Glide returned an invalid list")
        if action == "list_tables" and any(not isinstance(row.get("id"), str) or not isinstance(row.get("name"), str) for row in data):
            raise ValueError("Glide returned an invalid table")
        if action == "list_rows" and "continuation" in payload and not isinstance(payload["continuation"], str):
            raise ValueError("Glide returned an invalid continuation")
        if action == "import_table" and any(not isinstance(row.get("tableID"), str) or not isinstance(row.get("rowIDs"), list) for row in data):
            raise ValueError("Glide returned an invalid import result")
    elif not isinstance(data, dict):
        raise ValueError("Glide returned an invalid object")
    if action in {"create_table", "replace_table", "add_rows"}:
        if code == 202:
            if not isinstance(data.get("jobID"), str):
                raise ValueError("Glide returned no job ID")
        elif not isinstance(data.get("rowIDs"), list) or any(not isinstance(v, str) for v in data["rowIDs"]):
            raise ValueError("Glide returned invalid row IDs")
        if action == "create_table" and not isinstance(data.get("tableID"), str):
            raise ValueError("Glide returned no table ID")
    if action == "get_job" and data.get("status") not in {"running", "succeeded", "failed"}:
        raise ValueError("Glide returned an invalid job status")
    output = {"status": "success", "http_status": code, **payload}
    if code == 202:
        output.update(status="pending", completed=False)
    elif action == "get_job":
        output["completed"] = data["status"] != "running"
        if data["status"] == "failed":
            output["status"] = "error"
    return output


class GlideAppsNode(WorkflowNode):
    integration_type = "automation-glide-apps"
    connection_evidence = ConnectionEvidence(noun="Glide Big Tables", operation="list_tables", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return GlideNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Glide API token")
        op, token = self.config.config, self.config.credentials.api_token
        method, path, params, headers, body = _request_parts(op)
        headers.update(Authorization="Bearer " + token, Accept="application/json")
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, headers=headers,
                    **({"json": body} if body is not None else {}))
        except httpx.TransportError:
            output = {"status": "unknown" if writing else "error",
                "message": "Glide did not confirm the request. Inspect the table or stash before retrying a write.",
                "write_outcome": "unverified" if writing else None}
        else:
            if not 200 <= response.status_code < 300:
                # Keep the provider's rejection text for connection evidence, without reflecting credentials.
                try:
                    message = response.json()["error"]["message"]
                    if not isinstance(message, str):
                        raise ValueError()
                except (ValueError, KeyError, TypeError):
                    message = "Glide returned HTTP " + str(response.status_code)
                output = {"status": "error", "http_status": response.status_code,
                    "message": message.replace(token, "[redacted]"),
                    "write_outcome": "unverified" if writing and response.status_code >= 500 else None}
            else:
                try:
                    output = _response(op, response.status_code, response.json())
                except (ValueError, TypeError, KeyError):
                    output = {"status": "unknown" if writing else "error", "http_status": response.status_code,
                        "message": "Glide returned an unexpected response; inspect before retrying a write.",
                        "write_outcome": "unverified" if writing else None}
                etag = response.headers.get("etag")
                if etag is not None:
                    output["etag"] = etag
        await self.emit(output)
        return output
