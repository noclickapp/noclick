"""NetHunt CRM v2 operations, pinned to the provider's public OpenAPI contract."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://nethunt.com"


class NetHuntTokenCredential(BaseModel):
    model_config = ConfigDict(title="Nethunt CRM API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://nethunt.com/api/docs",
            "x-credential-instructions": "In NetHunt Settings → Integrations → API & MCP, create a token and paste it here. Use a v2 API token (nh_live_…), with access to the folders you want to automate. NoClick checks the connection by listing accessible folders.",
        })
    credential_type: Literal["nethunt_crm_api_token"] = "nethunt_crm_api_token"
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FolderInput(Input):
    folder_id: str = Field(..., min_length=1, title="Folder ID")


class RecordInput(FolderInput):
    record_id: str = Field(..., min_length=1, title="Record ID")


class FieldKeys(Input):
    field_keys: Literal["id", "label"] = Field("id", description="Use stable field IDs, or field labels, in request and response fields.")


class TimelineFields(FieldKeys):
    from_time: str | None = Field(None, description="Inclusive start: ISO date-time or epoch milliseconds.")
    to_time: str | None = Field(None, description="Inclusive end; use 23:59:59.999Z to include a whole day.")
    types: str | None = Field(None, description="Comma-separated categories: comment,email,campaign_email,call,chat,calendar,file,record_created,record_updated.")
    cursor: str | None = Field(None, max_length=4096, description="Previous nextCursor; keep all filters unchanged. Continue until absent, even after an empty page.")
    limit: int = Field(100, ge=1, le=1000)
    include_email_stats: bool = False


class ListFolders(Input):
    operation: Literal["list_folders"] = "list_folders"


class GetFolder(FolderInput):
    operation: Literal["get_folder"] = "get_folder"


class CreateFolder(Input):
    operation: Literal["create_folder"] = "create_folder"
    name: str = Field(..., min_length=1)
    description: str | None = None


class UpdateFolder(FolderInput):
    operation: Literal["update_folder"] = "update_folder"
    name: str = Field(..., min_length=1, description="New folder name.")


class CreateRecord(FolderInput, FieldKeys):
    operation: Literal["create_record"] = "create_record"
    fields: dict[str, Any] = Field(..., description="Friendly field values. The name key sets the display name. Dates must be epoch milliseconds at UTC midnight; read-only fields cannot be written.")


class UpdateRecord(RecordInput, FieldKeys):
    operation: Literal["update_record"] = "update_record"
    fields: dict[str, Any] = Field(..., description="Fields to change; null clears a field and omitted keys stay unchanged. Date fields require UTC-midnight epoch milliseconds.")


class GetRecord(RecordInput, FieldKeys):
    operation: Literal["get_record"] = "get_record"


class DeleteRecord(RecordInput):
    operation: Literal["delete_record"] = "delete_record"


class ListUpdatedRecords(FolderInput, FieldKeys):
    operation: Literal["list_updated_records"] = "list_updated_records"
    since: str | None = Field(None, description="ISO date-time, epoch milliseconds, or previous nextSince token. Defaults to 24 hours ago. Feed nextSince back into since to continue.")
    limit: int = Field(100, ge=1, le=1000)


class SearchRecords(FolderInput, FieldKeys):
    operation: Literal["search_records"] = "search_records"
    text: str = Field(..., min_length=1)
    limit: int = Field(25, ge=1, le=100)


class FilterRecords(FolderInput, FieldKeys):
    operation: Literal["filter_records"] = "filter_records"
    filter: dict[str, Any] = Field(default_factory=dict, description="Field conditions and _and/_or groups; omit conditions to match all records.")
    sort: list[dict[str, Literal[1, -1]]] | None = Field(None, max_length=3, description="Up to three single-key objects, each mapping a field to 1 (ascending) or -1 (descending).")
    cursor: str | None = Field(None, max_length=4096, description="Previous nextCursor; keep filter, sort and time zone unchanged.")
    time_zone: str = "UTC"
    limit: int = Field(100, ge=1, le=1000)

    @field_validator("sort")
    @classmethod
    def single_keys(cls, value):
        if value is not None and any(len(item) != 1 for item in value):
            raise ValueError("Each sort entry must contain exactly one field")
        return value


class ListRecordTimeline(RecordInput, TimelineFields):
    operation: Literal["list_record_timeline"] = "list_record_timeline"


class ListFolderTimeline(FolderInput, TimelineFields):
    operation: Literal["list_folder_timeline"] = "list_folder_timeline"


class GetTimelineContent(RecordInput):
    operation: Literal["get_timeline_content"] = "get_timeline_content"
    timeline_id: str = Field(..., min_length=1)


class AddComment(RecordInput):
    operation: Literal["add_comment"] = "add_comment"
    text: str = Field(..., min_length=1, max_length=65000, description="Plain text; @member@example.com mentions a workspace member and notifies them.")


class LogCall(RecordInput):
    operation: Literal["log_call"] = "log_call"
    text: str = Field(..., min_length=1, max_length=65000)
    time: str | int | None = Field(None, description="ISO date-time or epoch milliseconds; defaults to now.")
    duration: int | None = Field(None, ge=0, description="Call duration in whole milliseconds.")


NetHuntConfig = Annotated[Union[ListFolders, GetFolder, CreateFolder, UpdateFolder,
    CreateRecord, UpdateRecord, GetRecord, DeleteRecord, ListUpdatedRecords,
    SearchRecords, FilterRecords, ListRecordTimeline, ListFolderTimeline,
    GetTimelineContent, AddComment, LogCall], Field(discriminator="operation")]


class NetHuntFullConfig(NodeConfig[NetHuntConfig, NetHuntTokenCredential]):
    pass


# Each operation makes exactly one request to a published v2 operation.
ROUTES = {
    "list_folders": ("GET", "/api/v2/folders"),
    "get_folder": ("GET", "/api/v2/folders/{folder_id}"),
    "create_folder": ("POST", "/api/v2/folders"),
    "update_folder": ("PATCH", "/api/v2/folders/{folder_id}"),
    "create_record": ("POST", "/api/v2/folders/{folder_id}/records"),
    "update_record": ("PATCH", "/api/v2/folders/{folder_id}/records/{record_id}"),
    "get_record": ("GET", "/api/v2/folders/{folder_id}/records/{record_id}"),
    "delete_record": ("DELETE", "/api/v2/folders/{folder_id}/records/{record_id}"),
    "list_updated_records": ("GET", "/api/v2/folders/{folder_id}/records"),
    "search_records": ("GET", "/api/v2/folders/{folder_id}/records/search"),
    "filter_records": ("POST", "/api/v2/folders/{folder_id}/records/filter"),
    "list_record_timeline": ("GET", "/api/v2/folders/{folder_id}/records/{record_id}/timeline"),
    "list_folder_timeline": ("GET", "/api/v2/folders/{folder_id}/timeline"),
    "get_timeline_content": ("GET", "/api/v2/folders/{folder_id}/records/{record_id}/timeline/{timeline_id}/content"),
    "add_comment": ("POST", "/api/v2/folders/{folder_id}/records/{record_id}/timeline/comments"),
    "log_call": ("POST", "/api/v2/folders/{folder_id}/records/{record_id}/timeline/calls"),
}


def request_parts(config):
    values = config.model_dump(exclude_none=True)
    action = values.pop("operation")
    method, route = ROUTES[action]
    for key in ("folder_id", "record_id", "timeline_id"):
        if key in values:
            identifier = values.pop(key)
            # Avoid path normalization or traversal even for pasted IDs.
            if identifier in {".", ".."} or any(c in identifier for c in "/\\?#"):
                raise ValueError("Use a single NetHunt resource ID")
            route = route.replace("{" + key + "}", quote(identifier, safe=""))
    body_keys = {
        "create_folder": ("name", "description"), "update_folder": ("name",),
        "create_record": ("fields",), "update_record": ("fields",),
        "filter_records": ("filter", "sort", "cursor"),
        "add_comment": ("text",), "log_call": ("text", "time", "duration"),
    }.get(action)
    body = {k: values.pop(k) for k in body_keys if k in values} if body_keys else None
    aliases = {"field_keys": "fieldKeys", "time_zone": "timeZone", "from_time": "from", "to_time": "to", "include_email_stats": "includeEmailStats"}
    query = {aliases.get(k, k): str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
    return method, route, query, body


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class NetHuntCrmNode(WorkflowNode):
    integration_type = "automation-nethunt-crm"
    connection_evidence = ConnectionEvidence(noun="folders", operation="list_folders")

    @classmethod
    def get_config_model(cls):
        return NetHuntFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a NetHunt CRM API token")
        config = self.config.config
        method, path, params, body = request_parts(config)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                json=body, headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") or "Request rejected"
            except (ValueError, AttributeError):
                message = "NetHunt returned a non-JSON error"
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(str(message), credential.api_token)}
        if config.operation == "delete_record" and not response.content:
            output = {"status": "success", "http_status": response.status_code, "deleted_id": config.record_id}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("NetHunt response exceeds 10 MB; reduce the page limit")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Expected a JSON response from NetHunt") from None
            expected = list if config.operation == "list_folders" else dict
            if not isinstance(data, expected):
                raise ValueError("Unexpected NetHunt response shape")
            if isinstance(data, dict) and data.get("error"):
                return {"status": "error", "error": _redact(str(data.get("message") or data["error"]), credential.api_token)}
            output = {"status": "success", "http_status": response.status_code, "data": _redact(data, credential.api_token)}
        await self.emit(output)
        return output
