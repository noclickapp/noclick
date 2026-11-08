"""remove.bg API v1: one documented HTTP operation per workflow action.

Contract: https://www.remove.bg/api/swagger.yaml (1.0.0).
Image actions are presets of POST /removebg, never additional API endpoints.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.remove.bg/v1.0"


def operation(name, label):
    return Field(name, title=label, json_schema_extra={
        "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
    })


class RemoveBgAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Remove Bg API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.remove.bg/dashboard#api-key",
            "x-credential-instructions": "Copy your API key from the remove.bg dashboard. NoClick checks your credit balance to verify the key.",
        })
    credential_type: Literal["remove_bg_api_key"] = Field("remove_bg_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _URLSource(_Input):
    image_url: str = Field(..., min_length=1, max_length=8192,
        description="Public source JPG, PNG or WebP URL; remove.bg downloads it. Maximum 22 MB and 50 megapixels.",
        json_schema_extra={"format": "uri"})

    @field_validator("image_url", "bg_image_url", check_fields=False)
    @classmethod
    def url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise ValueError("Use an absolute HTTP or HTTPS image URL without embedded credentials")
        return value


class _Render(_Input):
    size: Literal["preview", "full", "auto"] = Field("preview", description="Preview costs 0.25 credits; full costs 1 credit. Auto uses the highest resolution available for the image and balance.")
    format: Literal["auto", "png", "jpg", "zip", "webp"] = "auto"
    type: Literal["auto", "car", "product", "person", "animal", "graphic", "transportation"] = "auto"
    semitransparency: bool = True
    roi: str | None = Field(None, max_length=200, description='Region of interest, e.g. "0% 0% 100% 100%".')


class GetAccount(_Input):
    operation: Literal["get_account"] = operation("get_account", "Get Account Balance")


class RemoveBackground(_URLSource, _Render):
    operation: Literal["remove_background"] = operation("remove_background", "Remove Background from URL")


class RemoveBackgroundBase64(_Render):
    operation: Literal["remove_background_base64"] = operation("remove_background_base64", "Remove Background from Base64 Image")
    image_file_b64: str = Field(..., min_length=1, max_length=30_758_232,
        description="Base64-encoded JPG, PNG or WebP, without a data URL prefix; maximum decoded size 22 MB.",
        json_schema_extra={"format": "byte", "contentMediaType": "image/png"})

    @field_validator("image_file_b64")
    @classmethod
    def encoded_image(cls, value):
        try:
            content = base64.b64decode(value, validate=True)
        except ValueError:
            raise ValueError("Use base64 image bytes without a data URL prefix") from None
        if not content or len(content) > 22 * 1024 * 1024:
            raise ValueError("Image must contain at most 22 MB of decoded bytes")
        return value


class CreateAlphaMask(_URLSource, _Render):
    operation: Literal["create_alpha_mask"] = operation("create_alpha_mask", "Create Alpha Mask")
    format: Literal["png"] = "png"


class ReplaceBackgroundColor(_URLSource, _Render):
    operation: Literal["replace_background_color"] = operation("replace_background_color", "Replace Background with Color")
    bg_color: str = Field(..., min_length=1, max_length=64, description="Color name or hex, e.g. green, fff or 81d4fa77.")


class ReplaceBackgroundImage(_URLSource, _Render):
    operation: Literal["replace_background_image"] = operation("replace_background_image", "Replace Background with Image")
    bg_image_url: str = Field(..., min_length=1, max_length=8192, json_schema_extra={"format": "uri"})


class CropToSubject(_URLSource, _Render):
    operation: Literal["crop_to_subject"] = operation("crop_to_subject", "Crop to Subject")
    crop_margin: str = Field("0", max_length=200, description="Margin in pixels or percent, e.g. 30px or 10%. One, two or four values.")


class ResizeSubject(_URLSource, _Render):
    operation: Literal["resize_subject"] = operation("resize_subject", "Scale and Position Subject")
    scale: str = Field("50%", max_length=32, description="Subject scale: 10% through 100%, or original.")
    position: str = Field("center", max_length=64, description="original, center, a percentage, or horizontal and vertical percentages.")


class AddShadow(_URLSource, _Render):
    operation: Literal["add_shadow"] = operation("add_shadow", "Add Subject Shadow")
    shadow_type: Literal["auto", "car", "3D", "drop", "none"] = "auto"
    shadow_opacity: str = Field("auto", max_length=16, description="auto or an opacity from 0 to 100.")


class SubmitImprovement(_URLSource):
    """Submit a poorly processed image to improve future remove.bg results."""
    operation: Literal["submit_improvement"] = operation("submit_improvement", "Submit Image to Improvement Program")
    image_filename: str | None = Field(None, max_length=255)
    tag: str | None = Field(None, max_length=255)
    agree_to_conditions: Literal[True] = Field(..., description="Submitting shares this image with remove.bg under https://www.remove.bg/ipc. Confirm that you agree to those conditions.")


Operation = Annotated[Union[GetAccount, RemoveBackground, RemoveBackgroundBase64,
    CreateAlphaMask, ReplaceBackgroundColor, ReplaceBackgroundImage, CropToSubject,
    ResizeSubject, AddShadow, SubmitImprovement], Field(discriminator="operation")]


class RemoveBgConfig(NodeConfig[Operation, RemoveBgAPIKeyCredential]):
    pass


class RemoveBgNode(WorkflowNode):
    integration_type = "automation-remove-bg"
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account balance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RemoveBgConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Attach a remove.bg API key")
        name = config.operation
        method, path = ("GET", "/account") if name == "get_account" else ("POST", "/improve" if name == "submit_improvement" else "/removebg")
        body = config.model_dump(exclude_none=True, exclude={"operation", "agree_to_conditions"})
        if name == "create_alpha_mask":
            body["channels"] = "alpha"
        elif name == "crop_to_subject":
            body["crop"] = True
        headers = {"X-API-Key": credential.api_key,
            "Accept": "application/json" if path != "/removebg" else "image/png, image/jpeg, image/webp, application/zip"}
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers,
                    **({"json": body} if method == "POST" else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Could not complete the remove.bg request"}
        if response.status_code != 200:
            try:
                errors = response.json().get("errors", [])
                message = "; ".join(e["title"] for e in errors if isinstance(e, dict) and isinstance(e.get("title"), str))
            except (ValueError, AttributeError, TypeError):
                message = ""
            return {"status": "error", "status_code": response.status_code,
                "error": (message or "remove.bg did not confirm the request").replace(credential.api_key, "[redacted]")[:2000]}
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        if path == "/removebg":
            if not response.content or not (mime.startswith("image/") or mime in {"application/zip", "application/x-zip-compressed"}):
                return {"status": "error", "error": "Expected an image or ZIP file from remove.bg"}
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/zip": "zip", "application/x-zip-compressed": "zip"}.get(mime, "bin")
            metadata = {key.lower().removeprefix("x-").replace("-", "_"): value
                for key, value in response.headers.items() if key.lower() in {
                    "x-type", "x-width", "x-height", "x-credits-charged", "x-foreground-top",
                    "x-foreground-left", "x-foreground-width", "x-foreground-height"}}
            return {"status": "success", "file": BinaryOutput(response.content, mime, "remove-bg." + ext), **metadata}
        try:
            result = response.json()
            if not isinstance(result, dict) or "errors" in result:
                raise ValueError()
            if path == "/account":
                attrs = result["data"]["attributes"]
                if not isinstance(attrs.get("credits"), dict) or not isinstance(attrs.get("api"), dict):
                    raise ValueError()
                return {"status": "success", "data": attrs}
            if not isinstance(result.get("id"), str) or not result["id"]:
                raise ValueError()
            return {"status": "success", "id": result["id"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            return {"status": "error", "error": "Unexpected remove.bg JSON response"}
