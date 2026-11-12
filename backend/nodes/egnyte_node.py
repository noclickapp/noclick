"""Egnyte file, sharing, comment and event automation using the public API.

One operation makes one documented API call. List operations return one page,
including the provider's cursor/count metadata, so workflows can page explicitly.
File path segments are encoded independently as required by the file-system docs:
https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation
"""
from __future__ import annotations

import hmac
import re
import secrets
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.egnyte_operations import EGNYTE_OPERATIONS
from nodes.oauth.egnyte_oauth import OAUTH_PROVIDER
from nodes.scopes.egnyte import EGNYTE_SCOPES
from utils.ssrf import guarded_async_client

WEBHOOK_DOCS = "https://developers.egnyte.com/integration/cfs/api-docs/webhooks"

AUTH_DOCS = "https://us-partner-integrations.egnyte.com/integration/cfs/api-docs/authentication"


class EgnyteOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Egnyte OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "egnyte",
        "x-oauth-scopes": EGNYTE_SCOPES.declared_scopes(),
        "x-credential-url": AUTH_DOCS,
    })
    credential_type: Literal["egnyte_oauth"] = Field("egnyte_oauth", json_schema_extra={"ui:hidden": True})
    account_host: str = Field(..., title="Egnyte account host", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., min_length=1, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token expiry")

    @field_validator("account_host")
    @classmethod
    def host(cls, value):
        return OAUTH_PROVIDER.validate_context({"account_host": value})["account_host"]

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="Egnyte token", key=True)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Path(_Input):
    path: str = Field(..., min_length=1, max_length=4096, description="Full Egnyte path, for example /Shared/Documents/report.pdf. Enter the original path, not URL-encoded text.")

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        parts = value.lstrip("/").split("/")
        if any(part in {"", ".", ".."} for part in parts) or any(ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError("Use an Egnyte file or folder path without empty or dot segments")
        return value


class GetUserInfo(_Input):
    operation: Literal["get_user_info"] = "get_user_info"


class GetFileOrFolder(_Path):
    operation: Literal["get_file_or_folder"] = "get_file_or_folder"
    list_content: bool = Field(False, description="Include folder contents or file versions. Returns one page.")
    count: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    sort_by: Optional[Literal["name", "last_modified", "uploaded_by"]] = None
    sort_direction: Optional[Literal["ascending", "descending"]] = None
    include_locks: Optional[bool] = None
    list_custom_metadata: Optional[bool] = None


class CreateFolder(_Path):
    operation: Literal["create_folder"] = "create_folder"


class _MoveCopy(_Path):
    destination: str = Field(..., min_length=1, description="Full destination path, including the new name when renaming.")
    permissions: Optional[Literal["keep_original", "inherit_from_parent"]] = None
    folder_options_mode: Optional[Literal["keep_source", "apply_destination"]] = None

    @field_validator("destination")
    @classmethod
    def valid_destination(cls, value):
        return _Path.valid_path(value)


class MoveItem(_MoveCopy):
    operation: Literal["move_item"] = "move_item"


class CopyItem(_MoveCopy):
    operation: Literal["copy_item"] = "copy_item"


class LockFile(_Path):
    operation: Literal["lock_file"] = "lock_file"
    lock_token: Optional[str] = Field(None, description="Optional token required to unlock the file later.")
    lock_timeout: int = Field(3600, ge=1, le=604800)


class UnlockFile(_Path):
    operation: Literal["unlock_file"] = "unlock_file"
    lock_token: str = Field(..., min_length=1)


class DeleteItem(_Path):
    operation: Literal["delete_item"] = "delete_item"
    entry_id: Optional[str] = Field(None, description="Delete only this file version when provided.")


class DownloadFile(_Path):
    operation: Literal["download_file"] = "download_file"
    entry_id: Optional[str] = Field(None, description="Download this revision instead of the current version.")


class SearchFiles(_Input):
    operation: Literal["search_files"] = "search_files"
    query: str = Field(..., min_length=3, max_length=100)
    offset: int = Field(0, ge=0)
    count: int = Field(20, ge=1, le=20)
    folder: Optional[str] = None
    type: Optional[Literal["FILE", "FOLDER"]] = None
    sort_by: Optional[Literal["last_modified", "size", "name", "score"]] = None
    sort_direction: Optional[Literal["ascending", "descending"]] = None


class ListLinks(_Input):
    operation: Literal["list_links"] = "list_links"
    path: Optional[str] = None
    username: Optional[str] = None
    type: Optional[Literal["file", "folder"]] = None
    accessibility: Optional[Literal["anyone", "password", "domain", "recipients"]] = None
    offset: int = Field(0, ge=0)
    count: int = Field(100, ge=1, le=500)


class CreateLink(_Path):
    operation: Literal["create_link"] = "create_link"
    type: Literal["file", "folder", "upload"] = Field(..., title="Link type")
    accessibility: Literal["anyone", "password", "domain", "recipients"] = Field("domain", description="Who may use the link. Domain restricts it to account users.")
    recipients: Optional[list[str]] = None
    password: Optional[str] = Field(None, json_schema_extra={"ui:widget": "password"})
    expiry_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Expiration date in YYYY-MM-DD format.")
    expiry_clicks: Optional[int] = Field(None, ge=1, le=10)
    notify: bool = False

    @model_validator(mode="after")
    def protection(self):
        if self.accessibility == "password" and not self.password:
            raise ValueError("A password-protected link requires a password")
        if self.accessibility == "recipients" and not self.recipients:
            raise ValueError("A recipients-only link requires recipients")
        return self


class _Link(_Input):
    link_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GetLink(_Link):
    operation: Literal["get_link"] = "get_link"


class DeleteLink(_Link):
    operation: Literal["delete_link"] = "delete_link"


class AddComment(_Path):
    operation: Literal["add_comment"] = "add_comment"
    body: str = Field(..., min_length=1, description="Comment text.")


class ListComments(_Input):
    operation: Literal["list_comments"] = "list_comments"
    file: Optional[str] = Field(None, description="Full item path. Omitting this lists domain comments and requires an admin token.")
    count: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0)


class _Comment(_Input):
    comment_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GetComment(_Comment):
    operation: Literal["get_comment"] = "get_comment"


class DeleteComment(_Comment):
    operation: Literal["delete_comment"] = "delete_comment"


class GetEventsCursor(_Input):
    operation: Literal["get_events_cursor"] = "get_events_cursor"


class ListEvents(_Input):
    operation: Literal["list_events"] = "list_events"
    id: int = Field(..., ge=0, description="Event cursor from get_events_cursor or the previous page. Poll at most every five minutes.")
    count: int = Field(50, ge=1, le=100)
    folder: Optional[str] = None
    suppress: Optional[Literal["app", "user"]] = None
    type: Literal["file_system", "note"] = "file_system"
    reverse: Literal["0", "1"] = "0"


class OnFileUploaded(WebhookTriggerConfigBase):
    """Egnyte documents fs:add_file for uploaded files and file versions."""

    operation: Literal["on_file_uploaded"] = Field("on_file_uploaded", title="On File Uploaded", json_schema_extra={
        "const": "on_file_uploaded", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On File Uploaded",
    })
    path: Optional[str] = Field(None, title="Folder paths", description="Optional comma-separated folder paths, including subfolders. Leave empty to watch all paths; maximum 100 paths.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Egnyte automatically", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True,
    })

    @field_validator("path")
    @classmethod
    def valid_paths(cls, value):
        if value is None or not value.strip():
            return None
        paths = [part.strip() for part in value.split(",")]
        if len(paths) > 100:
            raise ValueError("Choose at most 100 folder paths")
        for path in paths:
            _Path.valid_path(path)
            if not path.startswith("/"):
                raise ValueError("Use full Egnyte paths beginning with /")
        return ",".join(paths)


# Egnyte's own MCP server: agents get its tools through a person's Egnyte sign-in.
EgnyteMcpCredential = mcp_credential("egnyte", "https://mcp-server.egnyte.com/mcp", app="Egnyte")
EgnyteCredential = Union[EgnyteOAuthCredential, EgnyteMcpCredential]


EgnyteOperation = Annotated[Union[GetUserInfo, GetFileOrFolder, CreateFolder, MoveItem,
    CopyItem, LockFile, UnlockFile, DeleteItem, DownloadFile, SearchFiles, ListLinks,
    CreateLink, GetLink, DeleteLink, AddComment, ListComments, GetComment, DeleteComment,
    GetEventsCursor, ListEvents, OnFileUploaded], Field(discriminator="operation")]


class EgnyteConfig(NodeConfig[EgnyteOperation, EgnyteCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _route(template, values):
    for key in re.findall(r"{([^}]+)}", template):
        value = str(values.pop(key))
        encoded = "/".join(quote(part, safe="") for part in value.lstrip("/").split("/")) if key == "path" else quote(value, safe="")
        template = template.replace("{" + key + "}", encoded)
    return template


class EgnyteNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_replace_stale_endpoint = True
    integration_type = "automation-egnyte"
    credential_provider_labels = {"egnyte": "Egnyte Account"}
    scope_registry = EGNYTE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Egnyte account", identity_operation="get_user_info", identity_keys=("username",))

    @classmethod
    def get_config_model(cls):
        return EgnyteConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="egnyte",
        )

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        credential = EgnyteOAuthCredential.model_validate(credential)
        async with guarded_async_client(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                method, f"https://{credential.account_host}/pubapi{path}",
                headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json"},
                **({"json": body} if body is not None else {}),
            )
        # A previously removed subscription is already cleaned up.
        if method == "DELETE" and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise httpx.HTTPStatusError(f"Egnyte returned HTTP {response.status_code}", request=response.request, response=response)
        return response.json() if response.content else None

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        trigger = OnFileUploaded.model_validate(config)
        secret = secrets.token_urlsafe(32)
        # The docs define authHeader as the VALUE of the delivery's Authorization
        # header (not an HMAC, nor the header's name). See WEBHOOK_DOCS.
        body = {"url": webhook_url, "eventType": ["fs:add_file"], "authHeader": f"Bearer {secret}"}
        if trigger.path:
            body["path"] = trigger.path
        data = await cls._webhook_request(credential, "POST", "/v1/webhooks", body=body)
        if not isinstance(data, dict) or not data.get("webhookId"):
            raise ValueError("Egnyte did not return a webhook ID")
        return {"external_webhook_id": data["webhookId"], "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint = (config or {}).get("external_webhook_id")
        if not endpoint:
            return
        if not credential:
            raise ValueError("Connect Egnyte to remove this webhook")
        await cls._webhook_request(credential, "DELETE", f"/v1/webhooks/{quote(str(endpoint), safe='')}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        trigger = OnFileUploaded.model_validate(config)
        return {"path": trigger.path}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        header = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        return bool(secret and isinstance(header, str) and hmac.compare_digest(
            header.encode(), f"Bearer {secret}".encode()))

    @staticmethod
    def _uploaded_events(payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return []
        return [event for event in payload["data"] if isinstance(event, dict) and event.get("eventType") == "fs:add_file"]

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return bool(cls._uploaded_events(payload))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"events": cls._uploaded_events(payload)}

    @classmethod
    def resolve_agent_event(cls, output):
        events = output.get("events") if isinstance(output, dict) else None
        if not isinstance(events, list) or not events:
            return super().resolve_agent_event(output)
        lines = []
        for event in events:
            user = event.get("user") or {}
            data = event.get("data") or {}
            actor = user.get("displayName") or user.get("username") or user.get("email") or str(user.get("id", "Unknown user"))
            path = data.get("targetPath")
            lines.append(f"Egnyte file uploaded by {actor}" + (f": {path}" if path else ""))
            lines.append(f"Domain: {event.get('domain')}; time (Unix ms): {event.get('timestamp')}; event ID: {event.get('eventId')}")
            if data.get("targetEntryId"):
                lines.append(f"File version ID: {data['targetEntryId']}")
            if data.get("targetGroupId"):
                lines.append(f"File group ID: {data['targetGroupId']}")
            if path:
                lines.append(f"To act: get_file_or_folder or download_file with path={path}")
        first = events[0]
        return {"text": "\n".join(lines), "title": "Egnyte file uploaded",
                "conversation_key": f"{first.get('domain')}:{(first.get('data') or {}).get('targetGroupId') or first.get('eventId')}"}

    async def execute(self, inputs):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        if not isinstance(self.config, EgnyteConfig) or not self.config.credentials:
            raise ValueError("Connect an Egnyte account")
        config = self.config.config
        if isinstance(config, OnFileUploaded):
            return self.resolve_trigger_payload(inputs, config.model_dump())
        credential = self.config.credentials.model_dump()
        host = OAUTH_PROVIDER.validate_context({"account_host": credential["account_host"]})["account_host"]
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=OAUTH_PROVIDER.bind_refresh(credential),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="egnyte", caller_path="execute",
        )
        self.config.credentials = EgnyteOAuthCredential.model_validate(credential)
        method, template, _ = EGNYTE_OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = _route(template, values)
        params, body = {}, None
        if config.operation in {"create_folder", "move_item", "copy_item", "lock_file", "unlock_file"}:
            action = {"create_folder": "add_folder", "move_item": "move", "copy_item": "copy", "lock_file": "lock", "unlock_file": "unlock"}[config.operation]
            body = {"action": action, **values}
        elif method == "POST":
            body = values
        else:
            params = {key: (str(value).lower() if isinstance(value, bool) else value) for key, value in values.items()}
        async with guarded_async_client(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, f"https://{host}/pubapi{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream" if config.operation == "download_file" else "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        # A write acknowledgement is a provider response, not an independent read-back.
        # Do not retry mutations automatically or turn a timeout into success.
        if not 200 <= response.status_code < 300:
            raise httpx.HTTPStatusError(f"Egnyte returned HTTP {response.status_code}", request=response.request, response=response)
        if config.operation == "download_file":
            return {"file": BinaryOutput(response.content, response.headers.get("content-type", "application/octet-stream"), config.path.rsplit("/", 1)[-1])}
        if response.status_code == 204 or not response.content:
            if config.operation == "get_user_info":
                raise ValueError("Egnyte did not return an account identity")
            return {"status_code": response.status_code, "data": None}
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("errorCode")):
            raise ValueError("Egnyte returned an API error")
        if config.operation == "get_user_info":
            if not isinstance(data, dict) or not isinstance(data.get("username"), str) or not data["username"] or type(data.get("id")) is not int:
                raise ValueError("Egnyte did not return an account identity")
            return data
        return {"status_code": response.status_code, "data": data}
