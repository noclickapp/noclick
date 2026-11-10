"""FaceCheck v1.02 API: explicit upload, search, status, removal and credit reads.

Contract: https://facecheck.id/Swagger/v1/swagger.json
Authentication and search semantics: https://facecheck.id/en/Face-Search/API
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://facecheck.id"


class FaceCheckAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="facecheck.id API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://facecheck.id/en/Face-Search/API",
            "x-credential-instructions": "Paste the API token from your FaceCheck API account. Omit any Bearer prefix. Connecting reads remaining credits and engine status without submitting a search.",
        },
    )
    credential_type: Literal["facecheck_api_token"] = Field(
        "facecheck_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096,
                           repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetInfoConfig(_Config):
    """Read remaining account credits, engine availability and indexed face count."""
    operation: Literal["get_info"] = Field("get_info", title="Get Credits and Engine Status",
                                            json_schema_extra={"ui:hidden": True})


class UploadImageConfig(_Config):
    """Upload one image; use the returned id_search for subsequent operations."""
    operation: Literal["upload_image"] = Field("upload_image", title="Upload Search Image",
                                                json_schema_extra={"ui:hidden": True})
    image_base64: str = Field(..., title="Image (Base64)", min_length=1, max_length=14_000_000,
        description="Raw base64 image bytes, without a data URL prefix. Upload one image per call; supply id_search to add to an existing search.",
        json_schema_extra={"contentEncoding": "base64"})
    filename: str = Field("image.png", title="Image Filename", max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"] = Field("image/png", title="Image Content Type")
    id_search: str | None = Field(None, title="Existing Search ID",
                                   description="Leave empty to create a new search bundle.")
    reset_prev_images: bool = Field(False, title="Reset Previous Images",
                                      description="Remove previously uploaded images from this search bundle.")

    @field_validator("image_base64")
    @classmethod
    def image(cls, value):
        try:
            content = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Supply raw base64 image bytes") from None
        if not content or len(content) > 10_000_000:
            raise ValueError("Supply an image up to 10 MB")
        return value

    @field_validator("filename")
    @classmethod
    def file_name(cls, value):
        if not value or any(c in value for c in '/\\\r\n\x00') or value in {".", ".."}:
            raise ValueError("Use a filename without path separators or controls")
        return value


class _SearchID(_Config):
    id_search: str = Field(..., title="Search ID", min_length=1, max_length=512,
        description="id_search returned by Upload Search Image.")


class SearchConfig(_SearchID):
    """Submit or continue a search; one request returns progress or results."""
    operation: Literal["search"] = Field("search", title="Run Face Search",
                                           json_schema_extra={"ui:hidden": True})
    with_progress: bool = Field(True, title="Return Progress Immediately",
        description="True returns progress immediately; false waits for completion at the provider.")
    demo: bool = Field(True, title="Testing Mode",
        description="Search only the testing subset. Turn off to run a production search using account credits.")
    shady_only: bool | None = Field(None, title="Shady Only",
        description="Optional shady_only filter from the published API contract.")


class GetSearchStatusConfig(_SearchID):
    """Read progress or results without submitting a new search."""
    operation: Literal["get_search_status"] = Field("get_search_status", title="Get Search Status and Results",
                                                      json_schema_extra={"ui:hidden": True})


class DeleteImageConfig(_SearchID):
    """Remove one uploaded image from a search request, not from the web index."""
    operation: Literal["delete_image"] = Field("delete_image", title="Remove Search Image",
                                                json_schema_extra={"ui:hidden": True})
    id_pic: str = Field(..., title="Image ID", min_length=1, max_length=512,
                         description="id_pic from the upload response's input images.")


Operation = Annotated[Union[GetInfoConfig, UploadImageConfig, SearchConfig,
                            GetSearchStatusConfig, DeleteImageConfig], Field(discriminator="operation")]


class FaceCheckNodeConfig(NodeConfig[Operation, FaceCheckAPITokenCredential]):
    pass


class FaceCheckNode(WorkflowNode):
    integration_type = "automation-facecheck"
    connection_evidence = ConnectionEvidence(
        noun="FaceCheck account credits", operation="get_info", proves="reachability"
    )

    @classmethod
    def get_config_model(cls):
        return FaceCheckNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a FaceCheck API token")
        config = self.config.config
        token = self.config.credentials.api_token
        headers = {"Authorization": token, "Accept": "application/json"}
        kwargs = {}
        if isinstance(config, GetInfoConfig):
            path = "/api/info"
        elif isinstance(config, UploadImageConfig):
            path = "/api/upload_pic"
            kwargs = {
                "files": [
                    ("images", (config.filename, base64.b64decode(config.image_base64, validate=True), config.mime_type)),
                    *([("reset_prev_images", (None, "true", "text/plain"))] if config.reset_prev_images else []),
                    *([("id_search", (None, config.id_search, "text/plain"))] if config.id_search else []),
                ],
            }
        elif isinstance(config, DeleteImageConfig):
            path = "/api/delete_pic"
            kwargs = {"params": {"id_search": config.id_search, "id_pic": config.id_pic}}
        else:
            path = "/api/search"
            body = {"id_search": config.id_search}
            if isinstance(config, GetSearchStatusConfig):
                body.update(status_only=True, with_progress=True)
            else:
                body.update(status_only=False, with_progress=config.with_progress, demo=config.demo)
                if config.shady_only is not None:
                    body["shady_only"] = config.shady_only
            kwargs = {"json": body}
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.post(BASE + path, headers=headers, **kwargs)
        if not response.is_success:
            raise ValueError(f"FaceCheck HTTP {response.status_code}: " + response.text.replace(token, "[redacted]")[:2000])
        try:
            body = response.json()
        except ValueError:
            raise ValueError("FaceCheck returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("FaceCheck returned an invalid response object")
        if body.get("error"):
            raise ValueError("FaceCheck: " + str(body["error"]).replace(token, "[redacted]"))
        result = {"status": "success", "operation": config.operation, "data": body}
        await self.emit(result)
        return result
