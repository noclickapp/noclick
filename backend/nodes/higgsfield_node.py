"""Higgsfield asynchronous image/video generation using the published v2 contract.

Submissions return immediately; reads never poll or download output URLs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.higgsfield.ai"


class HiggsfieldAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Higgsfield API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.higgsfield.ai",
            "x-credential-instructions": "Paste your Higgsfield Console key ID and secret. Optionally paste an existing request ID from this account to verify access with a read. Without a request ID the connection is saved as unverified. No generation is submitted during connection.",
        })
    credential_type: Literal["higgsfield_api_key"] = Field("higgsfield_api_key", json_schema_extra={"ui:hidden": True})
    api_key_id: str = Field(..., title="API key ID", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_key_secret: str = Field(..., title="API key secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    verification_request_id: UUID | None = Field(None, title="Verification request ID", description="Optional existing request UUID owned by this account. Used only for the connection read and request picker.")

    @field_validator("api_key_id", "api_key_secret", mode="before")
    @classmethod
    def key_part(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value) or ":" in value:
            raise ValueError("Paste only the key ID or secret, without a header or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateSoulImage(_Input):
    """Submit a SOUL standard image generation; retrieve outputs after completion."""
    operation: Literal["generate_soul_image"] = "generate_soul_image"
    prompt: str
    num_images: int = Field(1, ge=1, le=4)
    resolution: Literal["2K", "4K"] = "2K"
    aspect_ratio: Literal["1:1", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "16:9", "9:16", "21:9"] = "4:3"


class _Kling(_Input):
    prompt: str
    duration: Literal[5, 10] = 5
    cfg_scale: float = Field(0.5, ge=0, le=1, multiple_of=0.01)
    negative_prompt: str = ""


class _ImageInput(_Input):
    image_url: str = Field(..., description="Publicly accessible input image URL", json_schema_extra={"format": "uri"})

    @field_validator("image_url")
    @classmethod
    def image_uri(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a public HTTP or HTTPS image URL")
        return value


class GenerateKlingProImageVideo(_Kling, _ImageInput):
    """Submit Kling 2.5 Turbo Pro image-to-video."""
    operation: Literal["generate_kling_pro_image_video"] = "generate_kling_pro_image_video"


class GenerateKlingProTextVideo(_Kling):
    """Submit Kling 2.5 Turbo Pro text-to-video."""
    operation: Literal["generate_kling_pro_text_video"] = "generate_kling_pro_text_video"


class GenerateKlingStandardImageVideo(_Kling, _ImageInput):
    """Submit Kling 2.5 Turbo Standard image-to-video."""
    operation: Literal["generate_kling_standard_image_video"] = "generate_kling_standard_image_video"


class _Hailuo(_Input):
    prompt: str
    duration: Literal[6, 10] = 6
    prompt_optimizer: bool = True


class GenerateHailuoImageVideo(_Hailuo, _ImageInput):
    """Submit MiniMax Hailuo 2.3 image-to-video."""
    operation: Literal["generate_hailuo_image_video"] = "generate_hailuo_image_video"


class GenerateHailuoTextVideo(_Hailuo):
    """Submit MiniMax Hailuo 2.3 text-to-video."""
    operation: Literal["generate_hailuo_text_video"] = "generate_hailuo_text_video"


class _Request(_Input):
    request_id: UUID = Field(..., json_schema_extra={"x-dynamic-options": {
        "field_name": "request_id", "allow_custom": True,
        "placeholder": "Choose verification request or paste request UUID",
    }})


class GetRequestStatus(_Request):
    """Read a request's current state and metadata once."""
    operation: Literal["get_request_status"] = "get_request_status"


class GetRequestOutputs(_Request):
    """Read output URLs once; outputs_ready is false until completed. Does not download files."""
    operation: Literal["get_request_outputs"] = "get_request_outputs"


class CancelRequest(_Request):
    """Cancel a queued request; acceptance does not prove cancellation has completed."""
    operation: Literal["cancel_request"] = "cancel_request"


class DeleteRequest(_Request):
    """Permanently delete finished request inputs, outputs, prompt and parameters. Billing records remain."""
    operation: Literal["delete_request"] = "delete_request"


# Higgsfield's own MCP server: agents get its tools through a person's Higgsfield sign-in.
HiggsfieldMcpCredential = mcp_credential("higgsfield", "https://mcp.higgsfield.ai/mcp", app="Higgsfield")
HiggsfieldCredential = Union[HiggsfieldAPIKeyCredential, HiggsfieldMcpCredential]


HiggsfieldConfig = Annotated[Union[GenerateSoulImage, GenerateKlingProImageVideo,
    GenerateKlingProTextVideo, GenerateKlingStandardImageVideo,
    GenerateHailuoImageVideo, GenerateHailuoTextVideo, GetRequestStatus,
    GetRequestOutputs, CancelRequest, DeleteRequest], Field(discriminator="operation")]


class HiggsfieldFullConfig(NodeConfig[HiggsfieldConfig, HiggsfieldCredential]):
    pass


GENERATION_PATHS = {
    "generate_soul_image": "/higgsfield-ai/soul/standard",
    "generate_kling_pro_image_video": "/kling-video/v2.5-turbo/pro/image-to-video",
    "generate_kling_pro_text_video": "/kling-video/v2.5-turbo/pro/text-to-video",
    "generate_kling_standard_image_video": "/kling-video/v2.5-turbo/standard/image-to-video",
    "generate_hailuo_image_video": "/minimax/hailuo-2.3/standard/image-to-video",
    "generate_hailuo_text_video": "/minimax/hailuo-2.3/standard/text-to-video",
}


class _RequestStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["queued", "in_progress", "nsfw", "failed", "completed", "canceled"]
    request_id: UUID


def _redact(value, credential):
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.api_key_secret, credential.api_key_id):
            value = value.replace(secret, "[redacted]")
    return value


class HiggsfieldNode(WorkflowNode):
    integration_type = "automation-higgsfield"
    credential_provider_labels = {"higgsfield": "Higgsfield Account"}
    connection_evidence = ConnectionEvidence(field="request_id", noun="Higgsfield requests")

    @classmethod
    def get_config_model(cls):
        return HiggsfieldFullConfig

    @staticmethod
    async def _request(credential, method, path, body=None):
        # Paths are fixed or contain a parsed UUID. Never follow status/output URLs
        # with credentials, never retry a submission, and never follow redirects.
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": f"Key {credential.api_key_id}:{credential.api_key_secret}", "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("detail", "Higgsfield rejected the request")
            except (ValueError, AttributeError):
                message = "Higgsfield returned a non-JSON error"
            message = _redact(str(message), credential)
            # Error envelope preserves provider text for the shared connection seam.
            return {"status": "error", "http_status": response.status_code, "error": message}
        if method == "POST" and path.endswith("/cancel") and response.status_code == 202 and not response.content:
            return {"status": "success", "http_status": 202, "cancellation_accepted": True}
        try:
            data = response.json()
            if method == "DELETE":
                if not isinstance(data, dict) or data.get("status") != "deleted":
                    raise ValueError("Missing deletion acknowledgement")
                UUID(data["request_id"])
            else:
                _RequestStatus.model_validate(data)
            expected = path.split("/")[2] if path.startswith("/requests/") else None
            if expected and data["request_id"] != expected:
                raise ValueError("Response request ID does not match the requested resource")
        except (ValueError, TypeError, KeyError):
            raise ValueError("Higgsfield returned an invalid request response") from None
        return _redact({"status": "success", "http_status": response.status_code, "data": data}, credential)

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, **kwargs):
        if field_name != "request_id":
            raise ValueError("Unknown Higgsfield field")
        credential = HiggsfieldAPIKeyCredential.model_validate(credential_data)
        if credential.verification_request_id is None:
            raise ValueError("Supply an existing verification request ID to prove account access")
        result = await cls._request(credential, "GET", f"/requests/{credential.verification_request_id}/status")
        if result["status"] == "error":
            return result
        data = result["data"]
        return {"options": [{"value": data["request_id"], "label": f"{data['request_id']} ({data['status']})"}]}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Higgsfield API key")
        config, credential = self.config.config, self.config.credentials
        operation = config.operation
        if operation in GENERATION_PATHS:
            result = await self._request(credential, "POST", GENERATION_PATHS[operation], config.model_dump(mode="json", exclude={"operation"}))
        else:
            path = f"/requests/{config.request_id}"
            method = "GET"
            if operation == "cancel_request":
                method, path = "POST", path + "/cancel"
            elif operation == "delete_request":
                method = "DELETE"
            else:
                path += "/status"
            result = await self._request(credential, method, path)
        if operation == "get_request_outputs" and result["status"] == "success":
            data = result["data"]
            result["outputs_ready"] = data["status"] == "completed"
            result["outputs"] = {k: data[k] for k in ("images", "video", "audio", "audios") if k in data}
        await self.emit(result)
        return result
