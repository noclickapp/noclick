"""AnyDB Ext Integration API 1.0.0: explicit, single-request operations.

Contract: https://www.anydb.com/openapi/spec.yaml
API-key setup: https://www.anydb.com/support/integrations/typescript-sdk/
List/search operations return one provider page, including its continuation fields.
File operations obtain URLs/complete uploads; they never fetch or send file bytes.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.anydb.com/api/integrations/ext"


class AnyDbCredential(BaseModel):
    model_config = ConfigDict(title="AnyDB API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.anydb.com/support/integrations/typescript-sdk/#getting-your-api-key",
        "x-credential-instructions": "In AnyDB, open the user icon, Profile Dialog, then Integration. Paste your API key and the email address of that AnyDB account. NoClick sends both as headers to app.anydb.com."})
    credential_type: Literal["any_db_api_key"] = Field("any_db_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    email: str = Field(..., min_length=3, max_length=320, title="Account email")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def account_email(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value.strip()):
            raise ValueError("Enter the AnyDB account email address")
        value = value.strip()
        if not value.isascii():
            raise ValueError("Use the ASCII account email address for the API header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Team(Input):
    teamid: str = Field(..., min_length=1, title="Team ID")


class Database(Team):
    adbid: str = Field(..., min_length=1, title="Database ID")


class Record(Database):
    adoid: str = Field(..., min_length=1, title="Record ID")


class CheckConnection(Input):
    """Validate the supplied API key and account email."""
    operation: Literal["check_connection"] = "check_connection"


class ListTeams(Input):
    """List the teams accessible to this account."""
    operation: Literal["list_teams"] = "list_teams"


class ListDatabases(Team):
    operation: Literal["list_databases"] = "list_databases"


class GetRecord(Record):
    operation: Literal["get_record"] = "get_record"


class ListRecords(Database):
    """Return one page; pass the returned lastmarker for the next page."""
    operation: Literal["list_records"] = "list_records"
    groupby: str | None = None
    templateid: str | None = None
    templatename: str | None = None
    parentid: str | None = None
    pagesize: int = Field(50, ge=1, le=1000)
    lastmarker: str | None = None
    sort: str | None = Field(None, description="Provider JSON string for sorting.")
    filter: str | None = Field(None, description="Provider JSON string for filters.")
    previewcells: str | None = Field(None, description="Provider JSON string for preview cells.")


class SearchRecords(Database):
    """Search one page of records; use start and limit to request another page."""
    operation: Literal["search_records"] = "search_records"
    search: str = Field(..., min_length=1, title="Search text")
    parentid: str | None = None
    start: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=1000)


class Cell(BaseModel):
    # The contract permits arbitrary provider cell attributes beyond key.
    model_config = ConfigDict(extra="allow")
    key: str | None = None


class CreateRecord(Database):
    operation: Literal["create_record"] = "create_record"
    name: str = Field(..., min_length=1, title="Record name")
    attach: str | None = None
    template: str | None = None
    templatename: str | None = None
    content: list[Cell] | None = Field(None, description="Array of provider cell objects, as specified by the pinned Ext API.")


class RecordMeta(Record):
    icon: str = Field(..., description="Required provider icon value; retain the record's existing icon when editing.")
    name: str | None = None
    description: str | None = None
    followup: float | None = None
    locked: StrictBool | None = None
    attach: str | None = None
    status: str | None = None
    assignees: dict[str, Any] | None = None


class UpdateRecord(Input):
    operation: Literal["update_record"] = "update_record"
    meta: RecordMeta
    content: list[Cell] | None = None


class GetUploadUrl(Record):
    """Get a direct upload URL; upload bytes separately, then complete the upload."""
    operation: Literal["get_upload_url"] = "get_upload_url"
    filename: str = Field(..., min_length=1)
    filesize: int = Field(..., ge=0)
    cellpos: str | None = None
    import_content: StrictBool | None = None
    import_media: StrictBool | None = None


class CompleteUpload(Database):
    """Finalize a file already uploaded using the provider's direct upload URL."""
    operation: Literal["complete_upload"] = "complete_upload"
    filesize: int = Field(..., ge=0)
    adoid: str | None = None
    cellpos: str | None = None
    import_content: StrictBool | None = None
    import_attachto: str | None = None
    import_templateid: str | None = None
    import_filename: str | None = None
    import_image: StrictBool | None = None


class GetDownloadUrl(Record):
    """Get the file URL response without following a redirect or downloading bytes."""
    operation: Literal["get_download_url"] = "get_download_url"
    cellpos: str = Field(..., min_length=1)
    preview: StrictBool = False


class RemoveRecord(Record):
    """Remove a record from the specified parents, rather than claim a hard delete."""
    operation: Literal["remove_record"] = "remove_record"
    removefromids: str | list[str] = Field(..., description="Parent IDs as a comma-separated string or array.")


class CopyRecord(Record):
    operation: Literal["copy_record"] = "copy_record"
    dstadbid: str | None = None
    attachto: str | None = None
    attachmentsmode: Literal["noattachments", "link", "duplicate"] = "noattachments"


class CreateShare(Record):
    operation: Literal["create_share"] = "create_share"
    role: Literal["viewer", "editor"] = "viewer"
    withattachments: str = Field(..., description="Provider string value for including attachments.")
    shared_userids: str | None = Field(None, description="Comma-separated user IDs.")
    shared_emails: str | None = Field(None, description="Comma-separated email addresses.")
    shared_groupids: str | None = Field(None, description="Comma-separated group IDs.")
    name: str | None = None
    share_expiry_enable: StrictBool | None = None
    share_expiry_date: str | None = None


class DeleteShare(Team):
    operation: Literal["delete_share"] = "delete_share"
    shareid: str = Field(..., min_length=1, title="Share ID")
    sharetype: Literal["form", "item"] = "item"


class RegisterWebhook(Team):
    """Register an external HTTPS receiver; subscribe separately to enable events."""
    operation: Literal["register_webhook"] = "register_webhook"
    url: str = Field(..., pattern=r"^https://[^\s]+$", title="Receiver URL")
    name: str = Field(..., min_length=1)
    description: str | None = None
    timeout: int | None = Field(None, ge=1000, le=300000)
    maxRetries: int | None = Field(None, ge=0, le=10)
    backoffMs: int | None = Field(None, ge=100, le=60000)
    customHeaders: dict[str, str] | None = None


class Webhook(Input):
    webhookId: str = Field(..., min_length=1, title="Webhook ID")


class Subscription(Webhook):
    event: Literal["RECORD_CREATE", "RECORD_UPDATE", "RECORD_DELETE"] = Field(..., description="Create/update events are debounced and may be delayed.")


class SubscribeWebhook(Subscription):
    operation: Literal["subscribe_webhook"] = "subscribe_webhook"


class UnsubscribeWebhook(Subscription):
    operation: Literal["unsubscribe_webhook"] = "unsubscribe_webhook"


class UpdateWebhook(Webhook):
    operation: Literal["update_webhook"] = "update_webhook"
    name: str | None = None
    description: str | None = None
    url: str | None = Field(None, pattern=r"^https://[^\s]+$")
    timeout: int | None = Field(None, ge=1000, le=300000)
    customHeaders: dict[str, str] | None = None


class DeleteWebhook(Webhook):
    operation: Literal["delete_webhook"] = "delete_webhook"


AnyDbOperation = Annotated[Union[
    CheckConnection, ListTeams, ListDatabases, GetRecord, ListRecords,
    SearchRecords, CreateRecord, UpdateRecord, GetUploadUrl, CompleteUpload,
    GetDownloadUrl, RemoveRecord, CopyRecord, CreateShare, DeleteShare,
    RegisterWebhook, SubscribeWebhook, UnsubscribeWebhook, UpdateWebhook, DeleteWebhook,
], Field(discriminator="operation")]


class AnyDbConfig(NodeConfig[AnyDbOperation, AnyDbCredential]):
    pass


# Each exposed operation maps to exactly one published operation.
ROUTES = {
    "check_connection": ("POST", "/checkauth"),
    "list_teams": ("GET", "/listteams"),
    "list_databases": ("GET", "/listdbsforteam"),
    "get_record": ("GET", "/record"),
    "list_records": ("GET", "/list"),
    "search_records": ("GET", "/search"),
    "create_record": ("POST", "/createrecord"),
    "update_record": ("PUT", "/updaterecord"),
    "get_upload_url": ("GET", "/getuploadurl"),
    "complete_upload": ("PUT", "/completeupload"),
    "get_download_url": ("GET", "/download"),
    "remove_record": ("DELETE", "/remove"),
    "copy_record": ("POST", "/copyrecord"),
    "create_share": ("PUT", "/share"),
    "delete_share": ("DELETE", "/share/{shareid}"),
    "register_webhook": ("POST", "/register"),
    "subscribe_webhook": ("POST", "/subscribe"),
    "unsubscribe_webhook": ("DELETE", "/unsubscribe"),
    "update_webhook": ("PUT", "/{webhookId}"),
    "delete_webhook": ("DELETE", "/{webhookId}"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class AnyDbNode(WorkflowNode):
    integration_type = "automation-any-db"
    connection_evidence = ConnectionEvidence(noun="teams", operation="list_teams", identity_operation="check_connection")

    @classmethod
    def get_config_model(cls):
        return AnyDbConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an AnyDB API key and account email")
        credential = self.config.credentials
        operation = self.config.config
        method, path = ROUTES[operation.operation]
        fields = operation.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("webhookId", "shareid"):
            if "{" + name + "}" in path:
                value = fields.pop(name)
                if value in {".", ".."} or any(c in value for c in "/\\?#%"):
                    raise ValueError("Use a single provider resource ID")
                path = path.replace("{" + name + "}", quote(value, safe=""))
        is_query = method == "GET" or operation.operation == "delete_share"
        if operation.operation == "get_download_url":
            fields["redirect"] = False
        headers = {"x-anydb-api-key": credential.api_key, "x-anydb-email": credential.email, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers,
                params=fields if is_query else None,
                json=fields if not is_query and fields else None)
        secrets = (credential.api_key,)
        if len(response.content) > 10_000_000:
            raise ValueError("AnyDB response exceeded the JSON size limit")
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "AnyDB returned a non-JSON response"}
        if not isinstance(body, dict):
            raise ValueError("Expected the AnyDB Result object")
        body = _redact(body, secrets)
        if not 200 <= response.status_code < 300 or body.get("success") is False or body.get("ok") is False or body.get("error"):
            error = body.get("reason") or body.get("message") or body.get("error") or "AnyDB rejected the request"
            return {"status": "error", "http_status": response.status_code, "error": error}
        return {"status": "success", "operation": operation.operation, "http_status": response.status_code, "data": body}
