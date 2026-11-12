"""Native ThoughtSpot v2 metadata, analytics data and report workflows.
Uses a supplied token on one public HTTPS tenant, without minting or refreshing
credentials. The node retains real permission, sampling and file-storage limits.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from email.utils import parsedate_to_datetime
from uuid import UUID

import httpx
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_serializer, model_validator
from nodes.core.base import WorkflowNode, NodeConfig, runtime_config_view
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import normalize_https_origin, guarded_async_client


FAMILY = "thoughtspot_access_token"
MAX_JSON = 2 * 1024 * 1024
MAX_REPORT = 10 * 1024 * 1024
ROUTES = {
    "auth/session/user": ("GET", 200),
    "auth/token/validate": ("POST", 200),
    "metadata/search": ("POST", 200),
    "metadata/answer/data": ("POST", 200),
    "metadata/liveboard/data": ("POST", 200),
    "searchdata": ("POST", 200),
    "report/answer": ("POST", 200),
    "report/liveboard": ("POST", 200),
    "metadata/copyobject": ("POST", 200),
    "metadata/delete": ("POST", 204),
    "metadata/tml/async/status": ("POST", 200),
}


def guid(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ThoughtSpot requires a resource GUID.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("ThoughtSpot requires a resource GUID.") from None


def integer(value: Any, *, minimum=0, maximum=2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("ThoughtSpot returned an invalid numeric field.")
    return value


def text(value: Any, *, maximum=10000, nonempty=False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (nonempty and not value.strip()):
        raise ValueError("ThoughtSpot returned an invalid text field.")
    return value


def retry_after(value):
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                return None
            seconds = math.ceil((stamp - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, min(86400, seconds))


async def request(credential, endpoint, *, body=None, report=False):
    if endpoint not in ROUTES or report != endpoint.startswith("report/"):
        raise ValueError("ThoughtSpot operation is not a supported native route.")
    method, expected_status = ROUTES[endpoint]
    url = credential["base_url"] + "/api/rest/2.0/" + endpoint
    headers = {
        "Authorization": "Bearer " + credential["access_token"],
        "Accept": "application/octet-stream" if report else "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NoClick-ThoughtSpot/2.0",
    }
    try:
        async with guarded_async_client(timeout=60.0, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, url, headers=headers, json=body) as response:
                status = response.status_code
                if status in (401, 403) or (endpoint == "auth/token/validate" and status == 400):
                    raise ValueError("ThoughtSpot authentication failed or access denied (401/403).")
                if status == 429:
                    wait = retry_after(response.headers.get("Retry-After"))
                    suffix = f" Retry after {wait} seconds." if wait is not None else ""
                    raise ValueError("ThoughtSpot rate limit reached (429)." + suffix)
                if status != expected_status:
                    raise ValueError(f"ThoughtSpot request failed (HTTP {status}); its outcome may be unknown.")
                cap = MAX_REPORT if report else MAX_JSON
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > cap:
                        raise ValueError("ThoughtSpot response exceeded the native size limit.")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                media = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
    except httpx.HTTPError:
        raise ValueError("ThoughtSpot transport failed; request outcome is unknown.") from None
    if expected_status == 204:
        if raw:
            raise ValueError("ThoughtSpot returned an unexpected body for HTTP 204.")
        return None
    if report:
        if media in ("application/json", "text/html") or media.endswith("+json"):
            raise ValueError("ThoughtSpot export returned an error or unexpected media.")
        if not raw:
            raise ValueError("ThoughtSpot export returned an empty file.")
        return raw, media
    if media != "application/json" and not media.endswith("+json"):
        raise ValueError("ThoughtSpot returned unexpected response media.")
    try:
        result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("ThoughtSpot returned malformed JSON.") from None
    if isinstance(result, dict) and any(result.get(k) is not None for k in ("error", "errors", "errorCode")):
        raise ValueError("ThoughtSpot returned a provider error envelope.")
    return result


async def validate_token(credential):
    value = await request(credential, "auth/token/validate", body={"token": credential["access_token"]})
    if not isinstance(value, dict) or not isinstance(value.get("scope"), dict):
        raise ValueError("ThoughtSpot returned malformed token status.")
    scope = value["scope"]
    if type(scope.get("org_id")) is not int or scope["org_id"] != credential["org_id"]:
        raise ValueError("ThoughtSpot token does not match the configured organization.")
    user_id = guid(value.get("valid_for_user_id"))
    if credential.get("expected_user_id") and user_id != credential["expected_user_id"]:
        raise ValueError("ThoughtSpot token does not match the configured user.")
    if value.get("token_type") != "BEARER":
        raise ValueError("ThoughtSpot returned an unsupported token type.")
    access_type = text(scope.get("access_type"), maximum=128, nonempty=True)
    metadata_id = guid(scope["metadata_id"]) if scope.get("metadata_id") else None
    if metadata_id != credential.get("scope_metadata_id") or (access_type != "FULL" and metadata_id is None):
        raise ValueError("ThoughtSpot token scope does not match the configured metadata binding.")
    if access_type == "FULL" and metadata_id:
        raise ValueError("ThoughtSpot returned an inconsistent full-token scope.")
    times = {}
    for key in ("creation_time_in_millis", "expiration_time_in_millis"):
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 2**53 - 1:
            raise ValueError("ThoughtSpot returned invalid token timestamps.")
        times[key] = number
    if times["expiration_time_in_millis"] <= datetime.now(timezone.utc).timestamp() * 1000:
        raise ValueError("ThoughtSpot authentication failed: token expired (401).")
    if times["creation_time_in_millis"] > times["expiration_time_in_millis"]:
        raise ValueError("ThoughtSpot returned inconsistent token timestamps.")
    return {**times, "valid_for_user_id": user_id, "token_type": "BEARER",
            "scope": {"org_id": scope["org_id"], "access_type": access_type, "metadata_id": metadata_id}}


def admit_scope(token, *, resource_id=None, full=False):
    bound = token["scope"]["metadata_id"]
    if full and (bound or token["scope"]["access_type"] != "FULL"):
        raise ValueError("This ThoughtSpot operation requires a full token and the provider's object permissions.")
    if bound and resource_id != bound:
        raise ValueError("ThoughtSpot operation is outside the token's bound metadata object.")


def metadata(value, *, expected_type, expected_id=None):
    if not isinstance(value, dict) or value.get("metadata_type") != expected_type:
        raise ValueError("ThoughtSpot returned mismatched metadata type.")
    item_id = guid(value.get("metadata_id"))
    if expected_id and item_id != expected_id:
        raise ValueError("ThoughtSpot returned metadata from a different resource.")
    header = value.get("metadata_header")
    if not isinstance(header, dict) or guid(header.get("id")) != item_id:
        raise ValueError("ThoughtSpot returned malformed metadata headers.")
    result = {"id": item_id, "name": text(value.get("metadata_name"), nonempty=True), "type": expected_type}
    if header.get("name") is not None and text(header["name"]) != result["name"]:
        raise ValueError("ThoughtSpot returned inconsistent resource names.")
    for key in ("description", "authorName", "authorDisplayName", "subType"):
        if header.get(key) is not None:
            result[key] = text(header[key])
    for key in ("author", "owner", "modifiedBy"):
        if header.get(key) is not None:
            result[key] = guid(header[key])
    for key in ("created", "modified"):
        if header.get(key) is not None:
            result[key] = integer(header[key])
    for key in ("isDeleted", "isHidden", "isPublished"):
        if header.get(key) is not None:
            if type(header[key]) is not bool:
                raise ValueError("ThoughtSpot returned an invalid metadata flag.")
            result[key] = header[key]
    if result.get("isDeleted"):
        raise ValueError("ThoughtSpot metadata is deleted.")
    if header.get("ownerOrgId") is not None:
        result["ownerOrgId"] = integer(header["ownerOrgId"])
    return result


def metadata_body(kind, *, resource_id=None, offset=0, limit=100, search=None, visualizations=False):
    select = {"type": kind}
    if resource_id:
        select["identifier"] = guid(resource_id)
    if search:
        select["name_pattern"] = search
    return {"metadata": [select], "include_headers": True, "include_details": False,
            "include_visualization_headers": visualizations, "include_hidden_objects": False,
            "include_incomplete_objects": False, "include_dependent_objects": False,
            "record_offset": offset, "record_size": limit}


async def search_metadata(credential, token, kind, *, resource_id=None, offset=0, limit=100,
                          search=None, visualizations=False, allow_absent=False):
    admit_scope(token, resource_id=resource_id, full=resource_id is None)
    raw = await request(credential, "metadata/search", body=metadata_body(kind, resource_id=resource_id,
                        offset=offset, limit=limit, search=search, visualizations=visualizations))
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError("ThoughtSpot returned an invalid metadata page.")
    items = [metadata(x, expected_type=kind, expected_id=resource_id) for x in raw]
    if resource_id and not items and not allow_absent:
        raise ValueError("ThoughtSpot resource not found or access denied.")
    if resource_id and len(items) > 1:
        raise ValueError("ThoughtSpot returned ambiguous resource metadata.")
    for item in items:
        if item.get("ownerOrgId") is not None and item["ownerOrgId"] != credential["org_id"]:
            raise ValueError("ThoughtSpot returned metadata from another organization.")
    return items, raw


def visualization_headers(raw, parent_id):
    value = raw.get("visualization_headers")
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("ThoughtSpot returned invalid visualization headers.")
    items, seen = [], set()
    for header in value:
        if not isinstance(header, dict):
            raise ValueError("ThoughtSpot returned malformed visualization metadata.")
        item_id = guid(header.get("id"))
        if item_id in seen:
            raise ValueError("ThoughtSpot returned duplicate visualizations.")
        seen.add(item_id)
        # Search is requested for one exact Liveboard; owner, if present, must
        # corroborate that hierarchy rather than a user's ownership.
        if header.get("owner") is not None and guid(header["owner"]) != parent_id:
            raise ValueError("ThoughtSpot visualization belongs to another Liveboard.")
        items.append({"id": item_id, "name": text(header.get("name"), nonempty=True), "liveboard_id": parent_id})
    return items


def data_response(raw, *, offset, limit, resource_id=None, visualization_ids=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("contents"), list) or len(raw["contents"]) > 100:
        raise ValueError("ThoughtSpot returned malformed data content.")
    if resource_id and guid(raw.get("metadata_id")) != resource_id:
        raise ValueError("ThoughtSpot returned data from another resource.")
    contents = []
    for chunk in raw["contents"]:
        if not isinstance(chunk, dict):
            raise ValueError("ThoughtSpot returned malformed data rows.")
        rows, cols = chunk.get("data_rows"), chunk.get("column_names")
        if not isinstance(rows, list) or len(rows) > limit or not isinstance(cols, list) or len(cols) > 200:
            raise ValueError("ThoughtSpot returned data beyond the requested page bounds.")
        cols = [text(col, maximum=1000) for col in cols]
        if len(set(cols)) != len(cols):
            raise ValueError("ThoughtSpot returned duplicate data column names.")
        returned = integer(chunk.get("returned_data_row_count"))
        available = integer(chunk.get("available_data_row_count"))
        if returned != len(rows) or (returned and available < offset + returned) or (not returned and available > offset) or integer(chunk.get("record_offset")) != offset or integer(chunk.get("record_size")) != limit:
            raise ValueError("ThoughtSpot returned inconsistent data pagination.")
        ratio = chunk.get("sampling_ratio")
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError("ThoughtSpot returned an invalid sampling ratio.")
        # FULL data format has keyed row objects. Only the documented columns
        # are returned; provider diagnostics and unknown top-level data are omitted.
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(cols):
                raise ValueError("ThoughtSpot returned rows inconsistent with FULL column metadata.")
            clean_rows.append({col: bounded_cell(row[col]) for col in cols})
        out = {"column_names": cols, "data_rows": clean_rows,
               "record_offset": offset, "record_size": limit, "returned_data_row_count": returned,
               "available_data_row_count": available, "sampling_ratio": ratio,
               "next_record_offset": offset + returned if returned and offset + returned < available else None}
        if visualization_ids is not None and chunk.get("visualization_id") is None:
            raise ValueError("ThoughtSpot returned data without the bound visualization identity.")
        if chunk.get("visualization_id") is not None:
            viz = guid(chunk["visualization_id"])
            if visualization_ids is not None and viz not in visualization_ids:
                raise ValueError("ThoughtSpot returned data for a different visualization.")
            out["visualization_id"] = viz
            if chunk.get("visualization_name") is not None:
                out["visualization_name"] = text(chunk["visualization_name"])
        contents.append(out)
    return {"metadata_id": resource_id, "contents": contents}


def bounded_cell(value, depth=0):
    if depth > 8:
        raise ValueError("ThoughtSpot data cell exceeded nesting bounds.")
    if value is None or type(value) in (str, bool, int):
        if isinstance(value, str) and len(value) > 10000:
            raise ValueError("ThoughtSpot data cell exceeded text bounds.")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list) and len(value) <= 100:
        return [bounded_cell(x, depth + 1) for x in value]
    if isinstance(value, dict) and len(value) <= 100 and all(isinstance(k, str) and len(k) <= 1000 for k in value):
        return {k: bounded_cell(v, depth + 1) for k, v in value.items()}
    raise ValueError("ThoughtSpot returned an unsupported data cell.")


def report_file(raw, *, file_format, liveboard):
    data, _ = raw
    if file_format == "PDF" and data.startswith(b"%PDF-"):
        return data, "application/pdf", "pdf"
    if file_format == "PNG" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png", "png"
    if file_format == "XLSX" and data.startswith(b"PK\x03\x04"):
        return data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if file_format == "CSV":
        if liveboard and data.startswith(b"PK\x03\x04"):
            return data, "application/zip", "zip"
        try:
            value = data.decode("utf-8-sig")
        except UnicodeError:
            raise ValueError("ThoughtSpot returned invalid CSV text.") from None
        if not value.strip() or value.lstrip().startswith(("<", "{", "[")) or "\0" in value:
            raise ValueError("ThoughtSpot returned invalid CSV report media.")
        return data, "text/csv", "csv"
    raise ValueError("ThoughtSpot export file signature does not match its requested format.")


def _guid_field(field, title, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return Field(..., title=title, json_schema_extra={"x-dynamic-options": options})


class ThoughtSpotAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="ThoughtSpot", extra="ignore", json_schema_extra={
        "x-credential-url": "https://developers.thoughtspot.com/docs/api-authv2"})
    credential_type: Literal["thoughtspot_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="ThoughtSpot Tenant", description="Public HTTPS cluster origin, without /api or a path.")
    access_token: str = Field(..., title="Bearer Access Token", description="Already-issued scoped token. NoClick does not mint or refresh it.", json_schema_extra={"ui:widget": "password"})
    org_id: int = Field(..., ge=0, le=2**31 - 1, strict=True, title="ThoughtSpot Organization ID", description="Active org_id from the token scope. It is verified before operations; no organization switching occurs.")
    scope_metadata_id: str | None = Field(None, title="Token Object GUID", description="Required for an object-scoped token. Leave empty for a full token; the provider scope is checked.")
    expected_user_id: str | None = Field(None, title="Expected User GUID", description="Optional user binding checked against actual token and session evidence.")
    expires_at: str | None = Field(None, title="Known Token Expiry", description="ISO timestamp with timezone. Omission means unknown; actual expiry is checked with token validation.")

    @field_validator("base_url")
    @classmethod
    def _origin(cls, value):
        try:
            return normalize_https_origin(value)
        except Exception:
            raise ValueError("Enter a public HTTPS ThoughtSpot tenant origin.") from None

    @field_validator("access_token")
    @classmethod
    def _token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(not 33 <= ord(c) <= 126 for c in value):
            raise ValueError("Enter a valid already-issued ThoughtSpot token.")
        return value

    @field_validator("scope_metadata_id", "expected_user_id")
    @classmethod
    def _optional_guid(cls, value):
        return guid(value) if value else None

    @field_validator("expires_at")
    @classmethod
    def _expiry(cls, value):
        if value is None:
            return None
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError()
            if stamp <= datetime.now(timezone.utc):
                raise ValueError()
            return stamp.isoformat()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("ThoughtSpot token expiry must be a future timestamp with timezone.") from None

    @model_serializer(mode="wrap")
    def _with_family(self, handler):
        return {**handler(self), "credential_type": FAMILY}


# ThoughtSpot's own MCP server: agents get its tools through a person's ThoughtSpot sign-in.
ThoughtspotMcpCredential = mcp_credential("thoughtspot", "https://agent.thoughtspot.app/mcp?api-version=latest", app="ThoughtSpot")
ThoughtSpotCredential = Union[ThoughtSpotAccessTokenCredential, ThoughtspotMcpCredential]


def shape_credential(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILY) != FAMILY:
        raise ValueError("Connect a ThoughtSpot access-token credential.")
    try:
        return ThoughtSpotAccessTokenCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("ThoughtSpot credential shape, tenant, organization or expiry is invalid.") from None


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("liveboard_id", "answer_id", "data_source_id", "visualization_id", "task_id", check_fields=False)
    @classmethod
    def _resource_guid(cls, value):
        return guid(value) if value is not None else None


class _Page(_Config):
    record_offset: int = Field(0, ge=0, le=100000, strict=True, title="Record Offset")
    record_size: int = Field(100, ge=1, le=100, strict=True, title="Page Size", description="One bounded page; -1/unbounded requests are excluded.")


class GetCurrentUser(_Config):
    operation: Literal["get_current_user"] = "get_current_user"


class GetTokenStatus(_Config):
    operation: Literal["get_token_status"] = "get_token_status"


class ListLiveboards(_Page):
    operation: Literal["list_liveboards"] = "list_liveboards"
    name_pattern: str | None = Field(None, max_length=200, title="Name Pattern", description="Case-insensitive provider pattern; % is a wildcard.")


class ListAnswers(ListLiveboards):
    operation: Literal["list_answers"] = "list_answers"


class ListDataSources(ListLiveboards):
    operation: Literal["list_data_sources"] = "list_data_sources"


class _Liveboard(_Config):
    liveboard_id: str = _guid_field("liveboard_id", "Liveboard")


class _Answer(_Config):
    answer_id: str = _guid_field("answer_id", "Saved Answer")


class _DataSource(_Config):
    data_source_id: str = _guid_field("data_source_id", "Data Source")


class GetLiveboard(_Liveboard):
    operation: Literal["get_liveboard"] = "get_liveboard"


class GetAnswer(_Answer):
    operation: Literal["get_answer"] = "get_answer"


class GetDataSource(_DataSource):
    operation: Literal["get_data_source"] = "get_data_source"


class ListLiveboardVisualizations(_Liveboard):
    operation: Literal["list_liveboard_visualizations"] = "list_liveboard_visualizations"


_DOWNLOAD = {"x-requires-tier": True, "x-tier-label": "Requires object view access and applicable ThoughtSpot data-download privileges."}


class FetchLiveboardData(_Liveboard, _Page):
    model_config = ConfigDict(extra="ignore", json_schema_extra=_DOWNLOAD)
    operation: Literal["fetch_liveboard_data"] = "fetch_liveboard_data"
    visualization_id: str | None = Field(None, title="Visualization", json_schema_extra={"x-dynamic-options": {"field_name": "visualization_id", "depends_on": "liveboard_id", "searchable": True, "allow_custom": True}})


class FetchAnswerData(_Answer, _Page):
    model_config = ConfigDict(extra="ignore", json_schema_extra=_DOWNLOAD)
    operation: Literal["fetch_answer_data"] = "fetch_answer_data"


class SearchData(_DataSource, _Page):
    model_config = ConfigDict(extra="ignore", json_schema_extra=_DOWNLOAD)
    operation: Literal["search_data"] = "search_data"
    query_string: str = Field(..., min_length=1, max_length=4000, title="ThoughtSpot Query", description="Documented ThoughtSpot search tokens, for example [sales] by [store]. Executes a warehouse query; no SQL or Spotter call.", json_schema_extra={"ui:widget": "textarea"})

    @field_validator("query_string")
    @classmethod
    def _nonempty_query(cls, value):
        if not value.strip():
            raise ValueError("Enter a ThoughtSpot search query.")
        return value


class ExportLiveboardReport(FetchLiveboardData):
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-requires-tier": True, "x-tier-label": "Requires applicable detailed-data or visuals-download privileges; Liveboard CSV/XLSX requires Cloud 26.2+."})
    operation: Literal["export_liveboard_report"] = "export_liveboard_report"
    file_format: Literal["CSV", "XLSX", "PDF", "PNG"] = Field("PDF", title="Report Format")
    confirm_export: bool = Field(False, strict=True, title="Export This Report", description="Stores a report through the current native file-output seam. Review your data and storage policy.")

    @model_validator(mode="after")
    def _export_confirmed(self):
        if not self.confirm_export:
            raise ValueError("Confirm the ThoughtSpot report export.")
        return self


class ExportAnswerReport(FetchAnswerData):
    model_config = ConfigDict(extra="ignore", json_schema_extra=_DOWNLOAD)
    operation: Literal["export_answer_report"] = "export_answer_report"
    file_format: Literal["CSV", "XLSX", "PDF", "PNG"] = "CSV"
    confirm_export: bool = Field(False, strict=True, title="Export This Report")

    @model_validator(mode="after")
    def _answer_export_confirmed(self):
        if not self.confirm_export:
            raise ValueError("Confirm the ThoughtSpot report export.")
        return self


class _Copy(_Config):
    title: str = Field(..., min_length=1, max_length=200, title="Copy Title")
    description: str = Field("", max_length=4000, title="Copy Description")
    confirm_copy: bool = Field(False, strict=True, title="Create Metadata Copy", description="Creates a real ThoughtSpot object. Its default visibility and notification behavior are provider-controlled.")

    @model_validator(mode="after")
    def _copy_confirmed(self):
        if not self.confirm_copy or not self.title.strip():
            raise ValueError("Confirm a named ThoughtSpot metadata copy.")
        return self


class CopyLiveboard(_Liveboard, _Copy):
    operation: Literal["copy_liveboard"] = "copy_liveboard"


class CopyAnswer(_Answer, _Copy):
    operation: Literal["copy_answer"] = "copy_answer"


class _Delete(_Config):
    expected_name: str = Field(..., min_length=1, max_length=200, title="Expected Current Name", description="Must match current readback. Only objects authored/owned by this token's current user are admitted.")
    confirm_delete: bool = Field(False, strict=True, title="Delete This Metadata Object", description="Deletes the real Answer or Liveboard; deletion can affect dependents. No cleanup runs automatically.")

    @model_validator(mode="after")
    def _delete_confirmed(self):
        if not self.confirm_delete:
            raise ValueError("Confirm ThoughtSpot metadata deletion.")
        return self


class DeleteOwnLiveboard(_Liveboard, _Delete):
    operation: Literal["delete_own_liveboard"] = "delete_own_liveboard"


class DeleteOwnAnswer(_Answer, _Delete):
    operation: Literal["delete_own_answer"] = "delete_own_answer"


class GetImportTaskStatus(_Config):
    model_config = ConfigDict(extra="ignore", json_schema_extra={"x-requires-tier": True, "x-tier-label": "Requires Cloud 10.4+ and access to your pre-existing TML import task."})
    operation: Literal["get_import_task_status"] = "get_import_task_status"
    task_id: str = Field(..., title="Existing TML Import Task GUID", description="Read-only status lookup; this node never submits TML imports.")


ThoughtSpotConfig = Annotated[Union[
    GetCurrentUser, GetTokenStatus, ListLiveboards, ListAnswers, ListDataSources,
    GetLiveboard, GetAnswer, GetDataSource, ListLiveboardVisualizations,
    FetchLiveboardData, FetchAnswerData, SearchData, ExportLiveboardReport, ExportAnswerReport,
    CopyLiveboard, CopyAnswer, DeleteOwnLiveboard, DeleteOwnAnswer, GetImportTaskStatus,
], Field(discriminator="operation")]


class ThoughtSpotFullConfig(NodeConfig[ThoughtSpotConfig, ThoughtSpotCredential]):
    pass


async def _profile(credential, token):
    raw = await request(credential, "auth/session/user")
    if not isinstance(raw, dict) or guid(raw.get("id")) != token["valid_for_user_id"]:
        raise ValueError("ThoughtSpot returned mismatched session identity.")
    org = raw.get("current_org")
    if not isinstance(org, dict) or type(org.get("id")) is not int or org["id"] != credential["org_id"]:
        raise ValueError("ThoughtSpot session belongs to a different organization.")
    if raw.get("deleted") is True or raw.get("account_status") not in (None, "ACTIVE"):
        raise ValueError("ThoughtSpot authentication failed: user is inactive (401).")
    return {"id": token["valid_for_user_id"], "name": text(raw.get("name"), nonempty=True),
            "display_name": text(raw.get("display_name"), nonempty=True),
            "current_org": {"id": org["id"], "name": text(org.get("name"), nonempty=True)}}


class ThoughtSpotNode(WorkflowNode):
    integration_type = "automation-thoughtspot"
    credential_provider_labels = {"thoughtspot": "ThoughtSpot Account"}
    agent_tool_provider = True
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", noun="ThoughtSpot user")

    @classmethod
    def get_config_model(cls):
        return ThoughtSpotFullConfig

    @classmethod
    def parse_config(cls, config_data):
        credentials = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(credentials, dict) and credentials.get("credential_type", FAMILY) != FAMILY:
            raise ValueError("Select a ThoughtSpot access-token credential.")
        try:
            return TypeAdapter(ThoughtSpotFullConfig).validate_python(runtime_config_view(config_data, ThoughtSpotFullConfig))
        except Exception:
            raise ValueError("ThoughtSpot configuration or credential fields are invalid.") from None

    async def execute(self, inputs):
        if not isinstance(self.config, ThoughtSpotFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a ThoughtSpot credential before running this operation.")
        credential = self.config.credentials.model_dump()
        credential = shape_credential(credential)
        token = await validate_token(credential)
        config = self.config.config
        operation = config.operation
        if operation == "get_token_status":
            return {"status": "success", "action": operation, "data": token}
        if operation == "get_current_user":
            return {"status": "success", "action": operation, "data": await _profile(credential, token)}
        if operation == "get_import_task_status":
            admit_scope(token, full=True)
            raw = await request(credential, "metadata/tml/async/status", body={
                "task_ids": [config.task_id], "author_identifier": token["valid_for_user_id"],
                "include_import_response": False, "record_size": 1, "record_offset": 0})
            if not isinstance(raw, dict) or not isinstance(raw.get("status_list"), list) or len(raw["status_list"]) != 1:
                raise ValueError("ThoughtSpot import task is unavailable or returned malformed status.")
            task = raw["status_list"][0]
            if not isinstance(task, dict) or guid(task.get("task_id")) != config.task_id or guid(task.get("author_id")) != token["valid_for_user_id"] or type(task.get("org_id")) is not int or task["org_id"] != credential["org_id"]:
                raise ValueError("ThoughtSpot import task belongs to another user or organization.")
            state = task.get("task_status")
            if state not in ("IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED"):
                raise ValueError("ThoughtSpot returned unknown import task status.")
            out = {"task_id": config.task_id, "task_status": state, "org_id": task["org_id"], "author_id": task["author_id"]}
            for key in ("total_object_count", "object_processed_count"):
                if task.get(key) is not None:
                    out[key] = integer(task[key])
            return {"status": "success", "action": operation, "data": out}
        kind = "LIVEBOARD" if hasattr(config, "liveboard_id") or operation == "list_liveboards" else "ANSWER" if hasattr(config, "answer_id") or operation == "list_answers" else "LOGICAL_TABLE"
        resource_id = getattr(config, "liveboard_id", None) or getattr(config, "answer_id", None) or getattr(config, "data_source_id", None)
        if operation.startswith("list_") and operation != "list_liveboard_visualizations":
            items, _ = await search_metadata(credential, token, kind, offset=config.record_offset,
                                                 limit=config.record_size, search=config.name_pattern)
            return {"status": "success", "action": operation, "data": items,
                    "record_offset": config.record_offset, "record_size": config.record_size,
                    "next_record_offset": config.record_offset + len(items) if len(items) == config.record_size else None,
                    "total_count": None, "pagination_is_snapshot": False}
        items, raw = await search_metadata(credential, token, kind, resource_id=resource_id,
                                               limit=1, visualizations=kind == "LIVEBOARD")
        current = items[0]
        if operation in ("get_liveboard", "get_answer", "get_data_source"):
            return {"status": "success", "action": operation, "data": current}
        visualizations = visualization_headers(raw[0], resource_id) if kind == "LIVEBOARD" else []
        if operation == "list_liveboard_visualizations":
            return {"status": "success", "action": operation, "data": visualizations}
        viz = getattr(config, "visualization_id", None)
        if viz and viz not in {x["id"] for x in visualizations}:
            raise ValueError("ThoughtSpot visualization is not in the configured Liveboard.")
        if operation in ("fetch_liveboard_data", "fetch_answer_data", "search_data"):
            endpoint = "metadata/liveboard/data" if kind == "LIVEBOARD" else "metadata/answer/data" if kind == "ANSWER" else "searchdata"
            body = {"record_offset": config.record_offset, "record_size": config.record_size, "data_format": "FULL"}
            if operation == "search_data":
                admit_scope(token, full=True)
                body.update(logical_table_identifier=resource_id, query_string=config.query_string)
            else:
                body["metadata_identifier"] = resource_id
                if viz:
                    body["visualization_identifiers"] = [viz]
            data = await request(credential, endpoint, body=body)
            projected = data_response(data, offset=config.record_offset, limit=config.record_size,
                                          resource_id=None if operation == "search_data" else resource_id,
                                          visualization_ids=({viz} if viz else {x["id"] for x in visualizations}) if kind == "LIVEBOARD" else None)
            return {"status": "success", "action": operation, "data": projected}
        if operation.startswith("export_"):
            from nodes.core.binary_output import BinaryOutput
            body = {"metadata_identifier": resource_id, "file_format": config.file_format,
                    "record_offset": config.record_offset, "record_size": config.record_size}
            if kind == "ANSWER":
                body["type"] = "SAVED"
            elif viz:
                body["visualization_identifiers"] = [viz]
            raw_report = await request(credential, "report/liveboard" if kind == "LIVEBOARD" else "report/answer", body=body, report=True)
            data, mime, extension = report_file(raw_report, file_format=config.file_format, liveboard=kind == "LIVEBOARD")
            return {"status": "success", "action": operation,
                    "file": BinaryOutput(data=data, content_type=mime, filename=f"thoughtspot-{resource_id}.{extension}"),
                    "metadata_id": resource_id, "file_format": config.file_format,
                    "storage_privacy_verified": False}
        if operation.startswith("copy_"):
            admit_scope(token, full=True)
            value = await request(credential, "metadata/copyobject",
                                      body={"identifier": resource_id, "type": kind, "title": config.title, "description": config.description})
            if not isinstance(value, dict):
                raise ValueError("ThoughtSpot copy outcome is unknown; inspect current metadata before retry.")
            try:
                created_id = guid(value.get("metadata_id"))
            except ValueError:
                raise ValueError("ThoughtSpot accepted copy without a usable ID; inspect metadata before retry.") from None
            if created_id == resource_id:
                raise ValueError("ThoughtSpot copy returned the original resource ID.")
            created, _ = await search_metadata(credential, token, kind, resource_id=created_id, limit=1)
            if created[0]["name"] != config.title or created[0].get("author") != token["valid_for_user_id"]:
                raise ValueError("ThoughtSpot copy readback does not match title/current author; inspect before retry.")
            return {"status": "success", "action": operation, "data": created[0], "readback_verified": True,
                    "visibility_verified": False, "notification_behavior_verified": False}
        if operation.startswith("delete_own_"):
            admit_scope(token, full=True)
            if current.get("author") != token["valid_for_user_id"] or current["name"] != config.expected_name:
                raise ValueError("ThoughtSpot delete requires the current author and exact expected name.")
            await request(credential, "metadata/delete", body={"metadata": [{"identifier": resource_id, "type": kind}],
                              "delete_disabled_objects": False})
            remaining, _ = await search_metadata(credential, token, kind, resource_id=resource_id, limit=1,
                                                      allow_absent=True)
            return {"status": "success", "action": operation, "metadata_id": resource_id,
                    "absence_observed": not remaining, "hard_erasure_verified": False}
        raise ValueError("ThoughtSpot operation is unsupported.")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        context = context if isinstance(context, dict) else {}
        credential = shape_credential(credential_data)
        fields = {"liveboard_id": "LIVEBOARD", "answer_id": "ANSWER", "data_source_id": "LOGICAL_TABLE", "visualization_id": "LIVEBOARD"}
        if field_name not in fields:
            return {"options": [], "next_page_token": None}
        parent = None
        if field_name == "visualization_id":
            parent = guid(context.get("liveboard_id"))
        search = search.strip() if isinstance(search, str) else None
        if search and len(search) > 200:
            raise ValueError("ThoughtSpot picker search exceeds its bound.")
        scope = hashlib.sha256(json.dumps([credential["base_url"], credential["org_id"], credential.get("scope_metadata_id"),
                                         credential.get("expected_user_id"), field_name, parent, search], separators=(",", ":")).encode()).hexdigest()
        offset = 0
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 512:
                    raise ValueError()
                cursor = json.loads(base64.urlsafe_b64decode(page_token.encode()))
                if cursor.get("scope") != scope:
                    raise ValueError()
                offset = integer(cursor.get("offset"), maximum=100000)
            except Exception:
                raise ValueError("ThoughtSpot picker cursor belongs to a different tenant, parent or search.") from None
        token = await validate_token(credential)
        if parent:
            _, raw = await search_metadata(credential, token, "LIVEBOARD", resource_id=parent, limit=1,
                                               visualizations=True)
            all_items = visualization_headers(raw[0], parent)
            if search:
                all_items = [item for item in all_items if search.lower() in item["name"].lower()]
            items = all_items[offset:offset + 100]
            more = offset + len(items) < len(all_items)
        else:
            items, _ = await search_metadata(credential, token, fields[field_name], offset=offset, limit=100, search=search)
            more = len(items) == 100
        next_token = base64.urlsafe_b64encode(json.dumps({"scope": scope, "offset": offset + len(items)}, separators=(",", ":")).encode()).decode() if more and offset + len(items) <= 100000 else None
        return {"options": [{"value": item["id"], "label": item["name"]} for item in items], "next_page_token": next_token}
