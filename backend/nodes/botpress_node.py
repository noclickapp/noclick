"""Botpress administration and table data operations using an existing user PAT.

Workspace administration is distinct from runtime/model/chat APIs. Data requests
are bound to the saved bot and project only selected metadata and scalar columns.
"""
from __future__ import annotations

import hmac
import json
import math
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ORIGIN = "https://api.botpress.cloud"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_COLLECTION = 2000
ID_PATTERN = r"[A-Za-z0-9_-]{1,128}"
PRIVATE_COLUMN = re.compile(r"secret|password|token|credential|authorization|configuration|config", re.I)
SYSTEM_COLUMNS = {"id", "createdAt", "updatedAt", "computed", "stale", "similarity"}


def _operation(value: str, label: str, category: str) -> dict:
    return {"const": value, "ui:hidden": True, "x-display-name": label,
            "x-category": category, "x-is-trigger": False}


def _picker(field: str) -> dict:
    return {"x-dynamic-options": {"type": "botpress", "field": field}}


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value):
        raise ValueError("Select a Botpress resource ID")
    return value


def _table_name(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip():
        raise ValueError("Use a table name or ID of at most 128 characters")
    if value in {".", ".."} or any(c in value for c in "/\\%?#") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Table names cannot contain path or control characters")
    return value


def _cursor(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use the opaque next-page token returned by Botpress")
    return value


def _column(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
        raise ValueError("Use a top-level scalar column name")
    if value in SYSTEM_COLUMNS or PRIVATE_COLUMN.search(value):
        raise ValueError("System and credential/configuration columns are excluded")
    return value


class BotpressPATCredential(BaseModel):
    credential_type: Literal["botpress_pat"] = Field("botpress_pat", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=128, title="Workspace ID",
        description="Existing workspace accessible to the PAT's user.")
    bot_id: str = Field(..., min_length=1, max_length=128, title="Bot ID",
        description="Existing bot in this workspace. Table and file operations stay bound to this bot.")
    personal_access_token: str = Field(..., min_length=1, max_length=4096, repr=False, title="Personal Access Token",
        json_schema_extra={"ui:widget": "password"}, description="An existing user PAT; bot and integration access keys are different credentials.")
    model_config = ConfigDict(hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.botpress.cloud",
        "x-credential-instructions": "Use an existing Personal Access Token from your profile and copy the workspace and bot IDs. Current user/workspace permissions control access. Connection checks bot metadata; it does not establish human identity or permission for every write."})

    @field_validator("workspace_id", "bot_id", mode="before")
    @classmethod
    def ids(cls, value):
        return _identifier(value)

    @field_validator("personal_access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the existing PAT as text")
        value = clean_secret(value, field_name="Personal Access Token")
        if not value or not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError("PAT must be a single printable token")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("table", "name", mode="before", check_fields=False)
    @classmethod
    def table_identifier(cls, value):
        return _table_name(value)

    @field_validator("file_id", mode="before", check_fields=False)
    @classmethod
    def file_identifier(cls, value):
        return _identifier(value)


class _CursorPage(_Config):
    next_token: str | None = Field(None, max_length=4096, title="Next Page Token",
        description="Opaque next_token from the previous result. One complete bounded provider page is returned; no invented server page size.")
    sort_direction: Literal["asc", "desc"] = Field("asc", title="Sort Direction")

    @field_validator("next_token", mode="before")
    @classmethod
    def page_token(cls, value):
        return _cursor(value)


class BotpressGetWorkspace(_Config):
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra=_operation("get_workspace", "Get Workspace Metadata", "Administration"))


class BotpressListBots(_CursorPage):
    operation: Literal["list_bots"] = Field("list_bots", json_schema_extra=_operation("list_bots", "List Workspace Bots", "Administration"))
    dev: bool = Field(False, title="Development Bots", description="False lists production bots; true lists development bots.")
    sort_field: Literal["createdAt", "updatedAt"] = Field("createdAt", title="Sort Field")


class BotpressGetBoundBot(_Config):
    operation: Literal["get_bound_bot"] = Field("get_bound_bot", json_schema_extra=_operation("get_bound_bot", "Get Connected Bot Metadata", "Administration"))


class BotpressListTables(_Config):
    operation: Literal["list_tables"] = Field("list_tables", json_schema_extra=_operation("list_tables", "List Bot Tables", "Tables"))


class _Table(_Config):
    table: str = Field(..., min_length=1, max_length=128, title="Table", json_schema_extra=_picker("table"))


class BotpressGetTable(_Table):
    operation: Literal["get_table"] = Field("get_table", json_schema_extra=_operation("get_table", "Get Table Metadata", "Tables"))


class BotpressColumn(_Config):
    name: str = Field(..., min_length=1, max_length=64, title="Column Name")
    value_type: Literal["string", "number", "boolean"] = Field("string", title="Scalar Type")

    @field_validator("name", mode="before")
    @classmethod
    def column_name(cls, value):
        return _column(value)


class BotpressCreateTable(_Config):
    operation: Literal["create_table"] = Field("create_table", json_schema_extra=_operation("create_table", "Create Plain Data Table", "Tables"))
    name: str = Field(..., min_length=1, max_length=128, title="Table Name")
    columns: list[BotpressColumn] = Field(..., min_length=1, max_length=20, title="Scalar Columns",
        description="Creates a factor-1 table with computation disabled and no searchable/computed columns. Stores data and consumes normal table quota.")

    @field_validator("columns")
    @classmethod
    def unique_columns(cls, value):
        if len({v.name for v in value}) != len(value):
            raise ValueError("Column names must be unique")
        return value


class BotpressDeleteTable(_Table):
    operation: Literal["delete_table"] = Field("delete_table", json_schema_extra=_operation("delete_table", "Delete Plain Data Table", "Tables"))
    confirm_delete: Literal[True] = Field(..., title="Confirm Permanent Table Deletion",
        description="Permanently removes this table and its rows; workflows using it can be affected.")


class _Selection(_Table):
    columns: list[str] = Field(..., min_length=1, max_length=20, title="Returned Scalar Columns",
        description="Explicit top-level projection. System IDs/timestamps remain; secrets, configuration, computed diagnostics and nested values are omitted.")

    @field_validator("columns")
    @classmethod
    def selected_columns(cls, value):
        result = [_column(v) for v in value]
        if len(set(result)) != len(result):
            raise ValueError("Select each column once")
        return result


class BotpressFindRows(_Selection):
    operation: Literal["find_rows"] = Field("find_rows", json_schema_extra=_operation("find_rows", "Find Table Rows", "Rows"))
    limit: int = Field(25, ge=1, le=100, strict=True, title="Page Size")
    offset: int = Field(0, ge=0, le=1000000, strict=True, title="Offset")
    order_direction: Literal["asc", "desc"] = Field("asc", title="ID Sort Direction")


class BotpressGetRow(_Selection):
    operation: Literal["get_row"] = Field("get_row", json_schema_extra=_operation("get_row", "Get Table Row", "Rows"))
    row_id: int = Field(..., ge=1, le=2147483647, strict=True, title="Row ID")


class BotpressRow(_Config):
    values: dict[str, Any] = Field(..., min_length=1, max_length=20, title="Scalar Values",
        description="Top-level string, number, boolean or null values only, at most 4KB per row. No computed or credential fields.")

    @field_validator("values")
    @classmethod
    def scalar_values(cls, value):
        for key, item in value.items():
            _column(key)
            if item is not None and type(item) not in {str, bool, int, float}:
                raise ValueError("Row values must be scalar")
            if type(item) is float and not math.isfinite(item):
                raise ValueError("Row numbers must be finite")
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 4096:
            raise ValueError("Row values exceed 4KB")
        return value


class BotpressUpdatedRow(BotpressRow):
    row_id: int = Field(..., ge=1, le=2147483647, strict=True, title="Existing Row ID")


class BotpressCreateRows(_Table):
    operation: Literal["create_rows"] = Field("create_rows", json_schema_extra=_operation("create_rows", "Create Table Rows", "Rows"))
    rows: list[BotpressRow] = Field(..., min_length=1, max_length=50, title="Rows")


class BotpressUpdateRows(_Table):
    operation: Literal["update_rows"] = Field("update_rows", json_schema_extra=_operation("update_rows", "Update Table Rows", "Rows"))
    rows: list[BotpressUpdatedRow] = Field(..., min_length=1, max_length=50, title="Existing Rows")

    @field_validator("rows")
    @classmethod
    def unique_rows(cls, value):
        if len({v.row_id for v in value}) != len(value):
            raise ValueError("Update each row ID once")
        return value


class BotpressDeleteRows(_Table):
    operation: Literal["delete_rows"] = Field("delete_rows", json_schema_extra=_operation("delete_rows", "Delete Selected Table Rows", "Rows"))
    row_ids: list[Annotated[int, Field(ge=1, le=2147483647, strict=True)]] = Field(..., min_length=1, max_length=50, title="Existing Row IDs")

    @field_validator("row_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Delete each row ID once")
        return value


class BotpressListFiles(_CursorPage):
    operation: Literal["list_files"] = Field("list_files", json_schema_extra=_operation("list_files", "List Bot File Metadata", "Files"))
    sort_field: Literal["key", "size", "createdAt", "updatedAt", "status"] = Field("createdAt", title="Sort Field")
    indexed: bool | None = Field(None, title="Indexed Files Filter")


class BotpressGetFile(_Config):
    operation: Literal["get_file"] = Field("get_file", json_schema_extra=_operation("get_file", "Get File Metadata", "Files"))
    file_id: str = Field(..., min_length=1, max_length=128, title="File ID", json_schema_extra=_picker("file_id"))


BotpressOperation = Annotated[Union[BotpressGetWorkspace, BotpressListBots, BotpressGetBoundBot,
    BotpressListTables, BotpressGetTable, BotpressCreateTable, BotpressDeleteTable, BotpressFindRows,
    BotpressGetRow, BotpressCreateRows, BotpressUpdateRows, BotpressDeleteRows, BotpressListFiles,
    BotpressGetFile], Field(discriminator="operation")]


class BotpressNodeConfig(NodeConfig[BotpressOperation, BotpressPATCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class BotpressFailure(Exception):
    def __init__(self, message: str, category: str, http_status: int | None = None):
        super().__init__(message)
        self.category, self.http_status = category, http_status


def _credential(data: Any) -> BotpressPATCredential:
    if not isinstance(data, dict) or data.get("credential_type") != "botpress_pat":
        raise BotpressFailure("Botpress credential is unavailable or has the wrong type", "authority")
    try:
        return BotpressPATCredential.model_validate(data)
    except Exception:
        raise BotpressFailure("Botpress credential fields are invalid", "authority") from None


def _allowed(method: str, path: str) -> bool:
    if (method, path) in {("GET", "/v1/admin/bots"), ("GET", "/v1/tables"),
                         ("POST", "/v1/tables"), ("GET", "/v1/files")}:
        return True
    if method == "GET" and re.fullmatch(r"/v1/admin/(workspaces|bots)/" + ID_PATTERN, path):
        return True
    if method == "GET" and re.fullmatch(r"/v1/files/" + ID_PATTERN, path):
        return True
    match = re.fullmatch(r"/v1/tables/([A-Za-z0-9_.~%!-]+)(/row|/rows|/rows/find|/rows/delete)?", path)
    return bool(match) and ((match[2] is None and method in {"GET", "DELETE"}) or
        (match[2] == "/row" and method == "GET") or (match[2] == "/rows" and method in {"POST", "PUT"}) or
        (match[2] in {"/rows/find", "/rows/delete"} and method == "POST"))


async def _request(credential, method, path, body=None, params=None):
    if not _allowed(method, path):
        raise BotpressFailure("Unsupported Botpress route", "validation")
    headers = {"Authorization": "Bearer " + credential.personal_access_token, "Accept": "application/json"}
    if path.startswith("/v1/admin/bots"):
        headers["x-workspace-id"] = credential.workspace_id
    elif path.startswith(("/v1/tables", "/v1/files")):
        headers["x-bot-id"] = credential.bot_id
    try:
        async with guarded_async_client(timeout=httpx.Timeout(25.0, connect=8.0), follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, ORIGIN + path, headers=headers, json=body, params=params) as response:
                status = response.status_code
                if status != 200:
                    category = ("authentication" if status == 401 else "permission" if status == 403 else
                        "not_found" if status == 404 else "rate_limit" if status == 429 else
                        "validation" if status in {400, 409, 422} else "unavailable" if status >= 500 else "protocol")
                    raise BotpressFailure(f"Botpress request refused (HTTP {status})", category, status)
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise BotpressFailure("Botpress returned an unexpected content type", "protocol")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BODY_BYTES:
                        raise BotpressFailure("Botpress response exceeds the bounded limit", "response_limit")
                try:
                    result = json.loads(content)
                except Exception:
                    raise BotpressFailure("Botpress returned invalid JSON", "protocol") from None
                if not isinstance(result, dict):
                    raise BotpressFailure("Botpress returned an unexpected response shape", "protocol")
                return result
    except BotpressFailure:
        raise
    except Exception:
        raise BotpressFailure("Botpress request could not complete; saved validity is unverified", "transport") from None


FIELDS = {
    "workspace": {"id", "name", "createdAt", "updatedAt", "botCount", "blocked", "isPublic", "handle"},
    "bot": {"id", "name", "createdAt", "updatedAt", "deployedAt", "type"},
    "table": {"id", "name", "factor", "frozen", "keyColumn", "isComputeEnabled", "createdAt", "updatedAt"},
    "file": {"id", "botId", "key", "size", "contentType", "createdAt", "updatedAt", "status", "expiresAt"},
}


def _scalar(value):
    return value is None or (type(value) in {str, bool, int, float} and
        (type(value) is not float or math.isfinite(value)))


def _project(value, resource, *, selected_id=None, bot_id=None):
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise BotpressFailure("Botpress returned an invalid resource", "protocol")
    try:
        _identifier(value["id"])
    except ValueError:
        raise BotpressFailure("Botpress returned an invalid resource ID", "protocol") from None
    if selected_id is not None and value["id"] != selected_id:
        raise BotpressFailure("Botpress returned a different resource ID", "protocol")
    if bot_id is not None and value.get("botId") != bot_id:
        raise BotpressFailure("Botpress file belongs to a different bot", "protocol")
    if resource in {"workspace", "bot", "table"} and not isinstance(value.get("name"), str):
        raise BotpressFailure("Botpress omitted the resource name", "protocol")
    if resource == "bot" and (not isinstance(value.get("type"), str) or value["type"] not in {"studio", "adk", "desk"}):
        raise BotpressFailure("Botpress returned an unknown bot type", "protocol")
    if resource == "file" and (any(not isinstance(value.get(k), str) for k in ("key", "contentType", "status")) or
        type(value.get("size")) is not int or value["size"] < 0 or value["status"] not in {
            "upload_pending", "upload_failed", "upload_completed", "indexing_pending", "indexing_failed", "indexing_completed"}):
        raise BotpressFailure("Botpress returned invalid file metadata", "protocol")
    result = {k: v for k, v in value.items() if k in FIELDS[resource] and _scalar(v)}
    if resource == "table":
        schema = value.get("schema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict) or len(properties) > 20:
            raise BotpressFailure("Botpress returned an invalid table schema", "protocol")
        result["columns"] = [{"name": k, "type": v.get("type")} for k, v in properties.items()
            if isinstance(k, str) and not PRIVATE_COLUMN.search(k) and isinstance(v, dict) and isinstance(v.get("type"), str) and v["type"] in {"string", "number", "boolean"}]
    return result


def _records(payload, key, resource, *, bot_id=None):
    values = payload.get(key)
    if not isinstance(values, list) or len(values) > MAX_COLLECTION:
        raise BotpressFailure("Botpress returned an invalid or oversized collection", "protocol")
    return [_project(v, resource, bot_id=bot_id) for v in values]


def _paged(payload, key, resource, input_token, *, bot_id=None):
    rows = _records(payload, key, resource, bot_id=bot_id)
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise BotpressFailure("Botpress omitted the documented page metadata", "protocol")
    try:
        token = _cursor(meta.get("nextToken"))
    except ValueError:
        raise BotpressFailure("Botpress returned an invalid page token", "protocol") from None
    if token is not None and (token == input_token or not rows):
        raise BotpressFailure("Botpress returned inconsistent pagination", "protocol")
    return {key: rows, "next_token": token, "returned_count": len(rows)}


def _row(value, columns):
    if not isinstance(value, dict) or type(value.get("id")) is not int or not 1 <= value["id"] <= 2147483647:
        raise BotpressFailure("Botpress returned an invalid row ID", "protocol")
    return {k: v for k, v in value.items() if k in {"id", "createdAt", "updatedAt", *columns} and _scalar(v)}


def _row_list(payload, columns, limit):
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > limit:
        raise BotpressFailure("Botpress returned an invalid or oversized row list", "protocol")
    result = [_row(r, columns) for r in rows]
    if len({r["id"] for r in result}) != len(result):
        raise BotpressFailure("Botpress returned duplicate row IDs", "protocol")
    return result


def _notice_count(payload, field):
    values = payload.get(field, [])
    if not isinstance(values, list) or len(values) > MAX_COLLECTION or any(not isinstance(v, str) for v in values):
        raise BotpressFailure("Botpress returned an invalid partial-result receipt", "protocol")
    return len(values)


def _plain_table(payload, selected=None):
    table = payload.get("table")
    _project(table, "table")
    if selected is not None and selected != table["id"] and selected != table.get("name"):
        raise BotpressFailure("Botpress returned a different table", "protocol")
    if table.get("isComputeEnabled") is not False:
        raise BotpressFailure("Writes require an explicitly computation-disabled table", "validation")
    for column in table["schema"]["properties"].values():
        if not isinstance(column, dict):
            raise BotpressFailure("Table column schema is unavailable", "validation")
        options = column.get("x-zui", {})
        if not isinstance(options, dict) or options.get("computed") or options.get("searchable") is True:
            raise BotpressFailure("Computed or searchable table writes are excluded", "validation")
    return table


def _check_row_values(table, rows):
    properties = table["schema"]["properties"]
    for row in rows:
        for key, value in row.values.items():
            column = properties.get(key)
            if not isinstance(column, dict) or not isinstance(column.get("type"), str) or column["type"] not in {"string", "number", "boolean"}:
                raise BotpressFailure("Write values must address existing scalar columns", "validation")
            if value is None:
                if column.get("nullable") is False:
                    raise BotpressFailure("This column does not accept null", "validation")
            elif not ((column["type"] == "string" and type(value) is str) or
                      (column["type"] == "boolean" and type(value) is bool) or
                      (column["type"] == "number" and type(value) in {int, float})):
                raise BotpressFailure("Write values must match the column's scalar type", "validation")


class BotpressNode(WorkflowNode):
    integration_type = "automation-botpress"
    credential_provider_labels = {"botpress": "Botpress Account"}
    connection_evidence = ConnectionEvidence(noun="bots", operation="get_bound_bot",
        label_keys=("name", "id"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BotpressNodeConfig

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential = _credential(credential_data)
            result = await _request(credential, "GET", "/v1/admin/bots/" + credential.bot_id)
            _project(result.get("bot"), "bot", selected_id=credential.bot_id)
            return {"valid": True}
        except BotpressFailure as exc:
            rejected = exc.category in {"authority", "authentication", "permission"}
            return {"valid": False if rejected else None, "error": str(exc)}

    async def _current_credential(self):
        supplied = self.config.credentials
        if supplied is None:
            raise BotpressFailure("Connect a Botpress PAT credential", "authority")
        credential_id = self.node_data.get("credential_id")
        if not credential_id:
            return supplied
        if not self.user_id:
            raise BotpressFailure("Botpress credential authority is unavailable", "authority")
        from utils.credentials import resolve_credential_with_owner_fallback
        from utils.database_pool import get_native_pool
        try:
            data = await resolve_credential_with_owner_fallback(str(credential_id), self.user_id,
                self.node_data.get("_approval_pool") or get_native_pool(), org_id=self.organization_id, workflow_id=self.workflow_id)
            current = _credential(data)
        except Exception:
            raise BotpressFailure("Botpress credential is unavailable or access denied", "authority") from None
        if (current.workspace_id != supplied.workspace_id or current.bot_id != supplied.bot_id or
            not hmac.compare_digest(current.personal_access_token, supplied.personal_access_token)):
            raise BotpressFailure("Botpress credential changed; reload before retrying", "authority")
        return current

    async def _provider(self, credential, method, path, body=None, params=None):
        await self._current_credential()
        result = await _request(credential, method, path, body, params)
        await self._current_credential()
        return result

    async def _bound_bot(self, credential):
        result = await self._provider(credential, "GET", "/v1/admin/bots/" + credential.bot_id)
        return _project(result.get("bot"), "bot", selected_id=credential.bot_id)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        credential = _credential(credential_data)
        if field_name not in {"table", "file_id"}:
            return {"options": [], "next_page_token": None}
        # Stored socket lookup admission owns actor/row checks before this loader.
        membership = await _request(credential, "GET", "/v1/admin/bots/" + credential.bot_id)
        _project(membership.get("bot"), "bot", selected_id=credential.bot_id)
        if field_name == "table":
            if page_token is not None:
                raise BotpressFailure("The documented table list is unpaginated", "validation")
            rows = _records(await _request(credential, "GET", "/v1/tables"), "tables", "table")
            next_token = None
        else:
            try:
                token = _cursor(page_token)
            except ValueError:
                raise BotpressFailure("Invalid Botpress picker token", "validation") from None
            result = _paged(await _request(credential, "GET", "/v1/files", params={"nextToken": token} if token else {}),
                "files", "file", token, bot_id=credential.bot_id)
            rows, next_token = result["files"], result["next_token"]
        term = str(search or "")[:200].casefold()
        selected = [v for v in rows if not term or term in str(v.get("name") or v.get("key") or v["id"]).casefold()]
        return {"options": [{"value": v["id"], "label": v.get("name") or v.get("key") or v["id"],
            "metadata": {"workspace_id": credential.workspace_id, "bot_id": credential.bot_id,
                "resource_type": "table" if field_name == "table" else "file"}} for v in selected], "next_page_token": next_token}

    async def execute(self, inputs):
        config = self.config.config
        op = config.operation
        write = op in {"create_table", "delete_table", "create_rows", "update_rows", "delete_rows"}
        selected = getattr(config, "table", None) or getattr(config, "file_id", None)
        attempted = False
        try:
            credential = await self._current_credential()
            status = "success"
            if op == "get_workspace":
                payload = await self._provider(credential, "GET", "/v1/admin/workspaces/" + credential.workspace_id)
                data = {"workspace": _project(payload, "workspace", selected_id=credential.workspace_id)}
            elif op == "list_bots":
                params = {"dev": str(config.dev).lower(), "sortField": config.sort_field, "sortDirection": config.sort_direction}
                if config.next_token:
                    params["nextToken"] = config.next_token
                data = _paged(await self._provider(credential, "GET", "/v1/admin/bots", params=params), "bots", "bot", config.next_token)
            else:
                bot = await self._bound_bot(credential)
                if op == "get_bound_bot":
                    data = {"bots": [bot]}
                elif op == "list_tables":
                    rows = _records(await self._provider(credential, "GET", "/v1/tables"), "tables", "table")
                    data = {"tables": rows, "returned_count": len(rows), "pagination": "unpaginated"}
                elif op == "create_table":
                    schema = {"type": "object", "additionalProperties": True, "properties": {
                        column.name: {"type": column.value_type, "x-zui": {"index": index}} for index, column in enumerate(config.columns)}}
                    attempted = True
                    payload = await self._provider(credential, "POST", "/v1/tables", {"name": config.name,
                        "schema": schema, "factor": 1, "isComputeEnabled": False})
                    table = _plain_table(payload)
                    if table.get("name") != config.name or table.get("factor") != 1:
                        raise BotpressFailure("Botpress returned a different table name or factor", "protocol")
                    data = {"table": _project(table, "table")}
                elif op in {"list_files", "get_file"}:
                    if op == "get_file":
                        payload = await self._provider(credential, "GET", "/v1/files/" + config.file_id)
                        data = {"file": _project(payload.get("file"), "file", selected_id=config.file_id, bot_id=credential.bot_id)}
                    else:
                        params = {"sortField": config.sort_field, "sortDirection": config.sort_direction}
                        if config.next_token:
                            params["nextToken"] = config.next_token
                        if config.indexed is not None:
                            params["indexed"] = str(config.indexed).lower()
                        data = _paged(await self._provider(credential, "GET", "/v1/files", params=params), "files", "file", config.next_token, bot_id=credential.bot_id)
                else:
                    table_path = "/v1/tables/" + quote(config.table, safe="")
                    if op == "get_table":
                        payload = await self._provider(credential, "GET", table_path)
                        table = payload.get("table")
                        data = {"table": _project(table, "table")}
                        if config.table != table["id"] and config.table != table.get("name"):
                            raise BotpressFailure("Botpress returned a different table", "protocol")
                        for field in ("rows", "stale", "indexing"):
                            value = payload.get(field)
                            if type(value) not in {int, float} or (type(value) is float and not math.isfinite(value)) or value < 0:
                                raise BotpressFailure("Botpress omitted table counts", "protocol")
                            data[field] = value
                    elif op in {"find_rows", "get_row"}:
                        if op == "get_row":
                            payload = await self._provider(credential, "GET", table_path + "/row", params={"id": config.row_id})
                            row = _row(payload.get("row"), config.columns)
                            if row["id"] != config.row_id:
                                raise BotpressFailure("Botpress returned a different row", "protocol")
                            data = {"row": row}
                        else:
                            body = {"limit": config.limit, "offset": config.offset, "select": config.columns,
                                "orderBy": "id", "orderDirection": config.order_direction}
                            payload = await self._provider(credential, "POST", table_path + "/rows/find", body)
                            rows = _row_list(payload, config.columns, config.limit)
                            more = payload.get("hasMore")
                            if (type(more) is not bool or type(payload.get("offset")) is not int or type(payload.get("limit")) is not int or
                                payload["offset"] != config.offset or payload["limit"] != config.limit or (more and not rows)):
                                raise BotpressFailure("Botpress returned inconsistent row pagination", "protocol")
                            next_offset = config.offset + len(rows) if more else None
                            data = {"rows": rows, "has_more": more, "offset": config.offset,
                                "next_offset": next_offset if next_offset is None or next_offset <= 1000000 else None,
                                "warning_count": _notice_count(payload, "warnings")}
                    elif op in {"delete_table", "create_rows", "update_rows", "delete_rows"}:
                        table = _plain_table(await self._provider(credential, "GET", table_path), config.table)
                        if op in {"create_rows", "update_rows"}:
                            _check_row_values(table, config.rows)
                        attempted = True
                        if op == "delete_table":
                            payload = await self._provider(credential, "DELETE", table_path)
                            if payload != {}:
                                raise BotpressFailure("Botpress did not return the documented deletion receipt", "protocol")
                            data = {"deleted_table": config.table, "acknowledged": True}
                        elif op == "delete_rows":
                            payload = await self._provider(credential, "POST", table_path + "/rows/delete", {"ids": config.row_ids})
                            count = payload.get("deletedRows")
                            if type(count) is not int or not 0 <= count <= len(config.row_ids):
                                raise BotpressFailure("Botpress returned an invalid deletion count", "protocol")
                            data = {"requested_ids": config.row_ids, "deleted_rows": count}
                            if "job" in payload:
                                job = payload["job"]
                                if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not isinstance(job.get("status"), str):
                                    raise BotpressFailure("Botpress returned an invalid async deletion receipt", "protocol")
                                status = "accepted"
                                data.update({"job": {"id": job["id"], "status": job["status"]}, "mutation_outcome": "unverified"})
                        else:
                            values = [{**r.values, **({"id": r.row_id} if op == "update_rows" else {})} for r in config.rows]
                            payload = await self._provider(credential, "PUT" if op == "update_rows" else "POST", table_path + "/rows", {"rows": values, "waitComputed": False})
                            # Mutation receipts expose row IDs/timestamps, never echo data or raw provider errors.
                            rows = _row_list(payload, [], len(values))
                            errors = _notice_count(payload, "errors")
                            if op == "update_rows" and any(r["id"] not in {v.row_id for v in config.rows} for r in rows):
                                raise BotpressFailure("Botpress returned an unexpected updated row", "protocol")
                            status = "partial" if errors or len(rows) != len(values) else "success"
                            data = {"rows": rows, "requested_count": len(values), "error_count": errors,
                                "warning_count": _notice_count(payload, "warnings")}
                            if status == "partial":
                                data["mutation_outcome"] = "partial_or_unverified"
                    else:
                        raise BotpressFailure("Unsupported Botpress operation", "validation")
            return {"status": status, "workspace_id": credential.workspace_id, "bot_id": credential.bot_id, **data}
        except BotpressFailure as exc:
            return {"status": "error", "success": False, "error": str(exc), "category": exc.category,
                "http_status": exc.http_status, "selected_resource": selected,
                "mutation_outcome": "unverified" if attempted else "not_attempted" if write else None}
