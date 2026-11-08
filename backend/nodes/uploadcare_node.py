"""Uploadcare REST v0.7 operations with project-key HMAC authentication.

Each operation makes one documented REST call. List operations return one page;
use the returned `next` URL's `from` value as `from_time` on the next call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from email.utils import formatdate
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.uploadcare.com"
ACCEPT = "application/vnd.uploadcare-v0.7+json"


class UploadcareAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Uploadcare API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.uploadcare.com/projects/-/api-keys/",
            "x-credential-instructions": "Paste your Uploadcare project's public and secret API keys from Project settings → API keys. NoClick signs requests with the secret key using Uploadcare HMAC authentication. Connecting reads your project details; keys permit both reads and writes to that project.",
        })
    credential_type: Literal["uploadcare_api_key"] = Field("uploadcare_api_key", json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., min_length=1, max_length=4096, title="Public key")
    secret_key: str = Field(..., min_length=1, max_length=4096, title="Secret key", json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "secret_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or c == ":" for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetProject(_Input):
    """Read the connected project's name and settings."""
    operation: Literal["get_project"] = "get_project"


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000)
    from_time: Optional[str] = Field(None, description="Copy the from timestamp from the previous page's next URL.", json_schema_extra={"format": "date-time"})

    @field_validator("from_time")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Use a timestamp with timezone")
        return value


class ListFiles(_Page):
    """Read one page of files; pagination URLs are returned without being followed."""
    operation: Literal["list_files"] = "list_files"
    stored: Optional[StrictBool] = None
    removed: StrictBool = False
    ordering: Literal["datetime_uploaded", "-datetime_uploaded"] = "datetime_uploaded"


class _File(_Input):
    file_id: UUID = Field(..., description="Uploadcare file UUID.")


class GetFile(_File):
    """Read file details."""
    operation: Literal["get_file"] = "get_file"


class StoreFile(_File):
    """Store a temporary file permanently."""
    operation: Literal["store_file"] = "store_file"


class DeleteFile(_File):
    """Delete a file from Uploadcare storage."""
    operation: Literal["delete_file"] = "delete_file"


class CopyFile(_Input):
    """Copy a file or transformed CDN URL into this project's storage."""
    operation: Literal["copy_file"] = "copy_file"
    source: str = Field(..., min_length=1, max_length=4096, description="Uploadcare UUID or CDN URL, optionally including transformations.")
    store: Literal["true", "false"] = "false"

    @field_validator("source")
    @classmethod
    def source_value(cls, value):
        try:
            UUID(value)
        except ValueError:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError("Use a file UUID or a CDN URL") from None
        return value


class GetMetadata(_File):
    """Read all custom metadata for a file."""
    operation: Literal["get_metadata"] = "get_metadata"


class _MetadataKey(_File):
    key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.:\-]+$")

    @field_validator("key")
    @classmethod
    def bounded_segment(cls, value):
        if value in {".", ".."}:
            raise ValueError("Use a metadata key other than a dot path segment")
        return value


class GetMetadataValue(_MetadataKey):
    """Read one metadata value."""
    operation: Literal["get_metadata_value"] = "get_metadata_value"


class SetMetadataValue(_MetadataKey):
    """Create or replace one metadata value."""
    operation: Literal["set_metadata_value"] = "set_metadata_value"
    value: str = Field(..., min_length=1, max_length=512)


class DeleteMetadataValue(_MetadataKey):
    """Delete one metadata key."""
    operation: Literal["delete_metadata_value"] = "delete_metadata_value"


class GetTags(_File):
    """Read file tags."""
    operation: Literal["get_tags"] = "get_tags"


class ReplaceTags(_File):
    """Replace every tag; an empty array clears all tags."""
    operation: Literal["replace_tags"] = "replace_tags"
    tags: list[str] = Field(..., max_length=50)


class UpdateTags(_File):
    """Add and remove tags in a single request."""
    operation: Literal["update_tags"] = "update_tags"
    add: list[str] = Field(default_factory=list)
    delete: list[str] = Field(default_factory=list)


class ListGroups(_Page):
    """Read one page of file groups."""
    operation: Literal["list_groups"] = "list_groups"
    ordering: Literal["datetime_created", "-datetime_created"] = "datetime_created"


class _Group(_Input):
    group_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}~[1-9][0-9]*$", description="Group ID including ~file-count suffix.")


class GetGroup(_Group):
    """Read a file group."""
    operation: Literal["get_group"] = "get_group"


class DeleteGroup(_Group):
    """Delete a group; this does not delete the files in the group."""
    operation: Literal["delete_group"] = "delete_group"


class ListWebhooks(_Input):
    """Read the project's webhook subscriptions."""
    operation: Literal["list_webhooks"] = "list_webhooks"


WebhookEvent = Literal["file.uploaded", "file.infected", "file.stored", "file.deleted", "file.info_updated"]


class _WebhookTarget(_Input):
    target_url: str = Field(..., min_length=1, max_length=255, json_schema_extra={"format": "uri"})

    @field_validator("target_url")
    @classmethod
    def url(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("Use an HTTP or HTTPS webhook receiver URL")
        return value


class CreateWebhook(_WebhookTarget):
    """Create a webhook subscription to a receiver you control."""
    operation: Literal["create_webhook"] = "create_webhook"
    event: WebhookEvent
    is_active: StrictBool = True
    signing_secret: Optional[str] = Field(None, max_length=32, json_schema_extra={"ui:widget": "password"})
    version: Literal["0.7"] = "0.7"


class UpdateWebhook(_WebhookTarget):
    """Update a webhook's receiver and subscription settings."""
    target_url: Optional[str] = Field(None, min_length=1, max_length=255, json_schema_extra={"format": "uri"})
    operation: Literal["update_webhook"] = "update_webhook"
    webhook_id: int = Field(..., ge=1)
    event: Optional[WebhookEvent] = None
    is_active: Optional[StrictBool] = None
    signing_secret: Optional[str] = Field(None, max_length=32, json_schema_extra={"ui:widget": "password"})


class DeleteWebhook(_WebhookTarget):
    """Unsubscribe webhooks at the exact target URL."""
    operation: Literal["delete_webhook"] = "delete_webhook"


UploadcareConfig = Annotated[Union[GetProject, ListFiles, GetFile, StoreFile, DeleteFile,
    CopyFile, GetMetadata, GetMetadataValue, SetMetadataValue, DeleteMetadataValue,
    GetTags, ReplaceTags, UpdateTags, ListGroups, GetGroup, DeleteGroup,
    ListWebhooks, CreateWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]


class UploadcareFullConfig(NodeConfig[UploadcareConfig, UploadcareAPIKeyCredential]):
    pass


def _wire(op):
    """Build exactly one published operation; never follow provider-returned URLs."""
    action = op.operation
    data = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    if action == "get_project":
        return "GET", "/project/", {}, None, False
    if action in {"list_files", "list_groups"}:
        if "from_time" in data:
            data["from"] = data.pop("from_time")
        return "GET", "/files/" if action == "list_files" else "/groups/", data, None, False
    if action == "copy_file":
        return "POST", "/files/local_copy/", {}, data, False
    if action in {"get_group", "delete_group"}:
        return "GET" if action == "get_group" else "DELETE", "/groups/" + quote(op.group_id, safe="") + "/", {}, None, False
    if action == "list_webhooks":
        return "GET", "/webhooks/", {}, None, False
    if action in {"create_webhook", "update_webhook", "delete_webhook"}:
        route = "/webhooks/"
        method = "POST"
        if action == "update_webhook":
            route += str(data.pop("webhook_id")) + "/"
            method = "PUT"
        elif action == "delete_webhook":
            route += "unsubscribe/"
            method = "DELETE"
        return method, route, {}, data, True
    route = "/files/" + str(op.file_id) + "/"
    if action in {"get_file", "store_file", "delete_file"}:
        return {"get_file": "GET", "store_file": "PUT", "delete_file": "DELETE"}[action], route + ("" if action == "get_file" else "storage/"), {}, None, False
    if action == "get_metadata":
        return "GET", route + "metadata/", {}, None, False
    if action in {"get_metadata_value", "set_metadata_value", "delete_metadata_value"}:
        return {"get_metadata_value": "GET", "set_metadata_value": "PUT", "delete_metadata_value": "DELETE"}[action], route + "metadata/" + quote(op.key, safe="") + "/", {}, op.value if action == "set_metadata_value" else None, False
    if action in {"get_tags", "replace_tags", "update_tags"}:
        return {"get_tags": "GET", "replace_tags": "PUT", "update_tags": "PATCH"}[action], route + "tags/", {}, None if action == "get_tags" else {k: v for k, v in data.items() if k != "file_id"}, False
    raise ValueError("Unknown Uploadcare operation")


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items() if k not in {"signing_secret", "secret_key"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class UploadcareNode(WorkflowNode):
    integration_type = "automation-uploadcare"
    connection_evidence = ConnectionEvidence(noun="project", identity_operation="get_project", identity_keys=("name", "pub_key"))

    @classmethod
    def get_config_model(cls):
        return UploadcareFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect your Uploadcare project API keys")
        op = self.config.config
        credential = self.config.credentials
        method, path, params, body, form = _wire(op)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        query = urlencode(params)
        uri = path + ("?" + query if query else "")
        content_type = "application/x-www-form-urlencoded" if form else "application/json"
        if form:
            content = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in body.items()}).encode()
        else:
            content = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        date = formatdate(usegmt=True)
        signing = "\n".join([method, hashlib.md5(content).hexdigest(), content_type, date, uri])
        signature = hmac.new(credential.secret_key.encode(), signing.encode(), hashlib.sha1).hexdigest()
        headers = {"Accept": ACCEPT, "Content-Type": content_type, "Date": date,
            "Authorization": "Uploadcare " + credential.public_key + ":" + signature}
        secrets = [credential.secret_key, getattr(op, "signing_secret", None)]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + uri, headers=headers, content=content)
        except httpx.RequestError:
            raise ValueError("Uploadcare request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Do not leak an echoed Authorization header or signing secret.
            message = "request was not confirmed"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str):
                    message = _redact(detail, secrets + [credential.public_key, signature])[:500]
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"Uploadcare HTTP {response.status_code}: {message}")
        try:
            data = None if response.status_code == 204 or not response.content else response.json()
        except ValueError:
            raise ValueError("Uploadcare returned an invalid JSON response; inspect writes before retrying") from None
        output = _redact({"status": "success", "operation": op.operation,
            "http_status": response.status_code, "data": data}, secrets)
        await self.emit(output)
        return output
