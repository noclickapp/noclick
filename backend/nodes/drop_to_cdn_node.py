"""Drop to CDN's complete five-operation public API (OpenAPI 1.0.0).

Contract: https://api.droptocdn.com/v1/openapi.json
Uploads and published HTML are public; retention and size limits depend on plan.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.media_resolver import resolve_media_input
from utils.ssrf import guarded_async_client

BASE = "https://api.droptocdn.com/v1"


class DropToCdnAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Drop To Cdn API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://droptocdn.com/docs",
            "x-credential-instructions": "Copy your API key from Drop to CDN Dashboard → Settings. Paste only the key, without Bearer. NoClick sends it to api.droptocdn.com and lists your account's files to check the connection. Uploaded files and published HTML receive public CDN URLs; plan quotas and retention rules apply.",
        })
    credential_type: Literal["drop_to_cdn_api_key"] = Field("drop_to_cdn_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without Bearer")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFiles(Input):
    """Read one page of your files, newest first; choose cursor or page pagination."""
    operation: Literal["list_files"] = "list_files"
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, min_length=1, description="next_cursor from the previous response. Do not combine with page.")
    page: int | None = Field(None, ge=1, description="1-based page number. Do not combine with cursor.")

    @model_validator(mode="after")
    def pagination(self):
        if self.cursor is not None and self.page is not None:
            raise ValueError("Choose cursor or page, not both")
        return self


class FileInput(Input):
    file_id: str = Field(..., min_length=1, max_length=256, description="File ID returned by upload or list files")

    @field_validator("file_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#%") or any(c.isspace() for c in value):
            raise ValueError("Use a single file ID, not a URL or path")
        return value


class GetFile(FileInput):
    """Fetch metadata for a file owned by your account."""
    operation: Literal["get_file"] = "get_file"


class DeleteFile(FileInput):
    """Permanently delete a file and its public CDN URL."""
    operation: Literal["delete_file"] = "delete_file"


class Retention(Input):
    retention_days: int | None = Field(None, description="Omit to use your plan's retention. Custom retention is ignored on Free.")
    never_expire: StrictBool | None = Field(None, description="Skip expiration (paid plans only).")


class UploadFile(Retention):
    """Upload a file as multipart data and obtain a public CDN URL."""
    operation: Literal["upload_file"] = "upload_file"
    file: str = Field(..., min_length=1, description="File URL, workflow resource ID, data URI or base64. Uploads become publicly accessible; the provider rejects executables, scripts and web pages.", json_schema_extra={"ui:widget": "media_upload"})


class PublishPage(Retention):
    """Publish HTML as a public hosted page."""
    operation: Literal["publish_page"] = "publish_page"
    html: str = Field(..., min_length=1, description="HTML to publish publicly", json_schema_extra={"ui:widget": "code_editor", "ui:language": "html"})


Operation = Annotated[Union[ListFiles, GetFile, DeleteFile, UploadFile, PublishPage], Field(discriminator="operation")]


class DropToCdnConfig(NodeConfig[Operation, DropToCdnAPIKeyCredential]):
    pass


class DropToCdnNode(WorkflowNode):
    integration_type = "automation-drop-to-cdn"
    connection_evidence = ConnectionEvidence(operation="list_files", noun="files", label_keys=("original_name", "id"))

    @classmethod
    def get_config_model(cls):
        return DropToCdnConfig

    async def execute(self, inputs):
        if not isinstance(self.config, DropToCdnConfig) or self.config.credentials is None:
            raise ValueError("Connect a Drop to CDN API key")
        op, credential = self.config.config, self.config.credentials
        method, path, expected = "GET", "/files", 200
        kwargs = {}
        if isinstance(op, ListFiles):
            kwargs["params"] = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, FileInput):
            path += "/" + quote(op.file_id, safe="")
            if isinstance(op, DeleteFile):
                method, expected = "DELETE", 204
        else:
            method, expected = "POST", 201
            body = op.model_dump(include={"retention_days", "never_expire"}, exclude_none=True)
            if isinstance(op, PublishPage):
                path = "/pages"
                kwargs["json"] = {"html": op.html, **body}
            else:
                media = await resolve_media_input(op.file, max_bytes=100 * 1024 * 1024)
                kwargs["files"] = {"file": (media.filename, media.data, media.mime_type)}
                kwargs["data"] = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in body.items()}
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "Drop to CDN request failed; a write may have completed. Inspect your files before retrying."}
        if response.status_code != expected:
            message = "Drop to CDN did not confirm the operation"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        if isinstance(op, DeleteFile):
            return {"status": "success", "http_status": 204, "deleted_id": op.file_id}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Drop to CDN returned invalid JSON; inspect your files before retrying a write") from None
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Drop to CDN returned an unexpected response")
        if isinstance(op, ListFiles):
            if not isinstance(body.get("data"), list) or any(not isinstance(row, dict) for row in body["data"]):
                raise ValueError("Drop to CDN returned an invalid file list")
        return {"status": "success", "http_status": expected, "data": body}
