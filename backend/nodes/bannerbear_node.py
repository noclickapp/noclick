"""Bannerbear V5 image, animation, template and batch automation.

Official contract: https://api.bannerbear.com/v5/openapi.json (version 5.0).
Reference and response examples: https://developers.bannerbear.com/v5/.
V5 keys are workspace scoped and incompatible with V2 project keys.
Renders are asynchronous: create once, then retrieve by UID to inspect status/files.
Project webhooks can be managed in Bannerbear; this node is request/response only.
"""
from typing import Annotated, Any, Literal, Union
import json
import time
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.bannerbear.com/v5"


class BannerbearAPIKeyCredential(BaseModel):
    credential_type: Literal["bannerbear_api_key"] = Field(
        "bannerbear_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key",
        description="Your Bannerbear V5 workspace API key.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Bannerbear API Key",
        json_schema_extra={
            "x-credential-url": "https://app.bannerbear.com/v5/api_keys",
            "x-credential-instructions": "Create a V5 API key in Bannerbear → API Keys. Enable read and write for images, image_templates, animations, animation_templates and batches, or use an unscoped key. V2 keys are not compatible.",
        },
    )


def _operation(name: str, category: str):
    label = name.replace("_", " ").title()
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": category, "x-is-trigger": False,
    })


def _template(field_name: str):
    return Field(..., title="Template", min_length=1, description="Select a Bannerbear V5 template or paste its UID.",
        json_schema_extra={"x-dynamic-options": {"field_name": field_name, "searchable": True, "allow_custom": True}})


class BannerbearOperationConfig(BaseModel):
    # JSON text is editable in the form; references may supply native objects/lists.
    @field_validator("modifications", "items", "tags", mode="before", check_fields=False)
    @classmethod
    def encode_json_fields(cls, value, info):
        if info.field_name in {"modifications", "items", "tags"} and isinstance(value, (dict, list)):
            return json.dumps(value)
        return value


class BannerbearListConfig(BannerbearOperationConfig):
    page: int = Field(1, ge=1, title="Page", description="Page of results (25 items per page).")


class BannerbearUIDConfig(BannerbearOperationConfig):
    uid: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="UID", description="Bannerbear resource UID, not its URL.")


class BannerbearImagePayload(BannerbearOperationConfig):
    template: str = _template("image_template")
    modifications: Json[dict[str, Any]] = Field(
        ..., title="Modifications (JSON)", description='V5 object, for example {"objects":[{"name":"title","text":"Hello World"}]} — not a V2 modifications array.',
        json_schema_extra={"ui:widget": "textarea"},
    )
    formats: Json[list[Literal["jpg", "png", "pdf", "webp", "avif"]]] | None = Field(None, title="Formats (JSON)", description='Optional JSON array, e.g. ["png", "jpg"].', json_schema_extra={"ui:widget": "textarea"})
    scale: Literal[1, 2, 3, 4] | None = Field(None, title="Scale")
    dpi: int | None = Field(None, ge=72, le=600, title="Print DPI")
    quality: int | None = Field(None, ge=1, le=100, title="Compression Quality")
    proxy: bool | None = Field(None, title="Proxy External Images")
    metadata: str | None = Field(None, title="Metadata")
    version: int | None = Field(None, title="Template Version", description="Pin a saved template version.")

    @field_validator("formats", mode="before")
    @classmethod
    def encode_formats(cls, value):
        return json.dumps(value) if isinstance(value, list) else value


class BannerbearTemplateFields(BannerbearOperationConfig):
    description: str | None = Field(None, title="Description")
    tags: Json[list[str]] | None = Field(None, title="Tags (JSON)", description='Optional JSON array, e.g. ["social", "banner"].', json_schema_extra={"ui:widget": "textarea"})
    width: int | None = Field(None, ge=100, le=5000, title="Width", description="Canvas width in pixels.")
    height: int | None = Field(None, ge=100, le=5000, title="Height", description="Canvas height in pixels.")


class BannerbearGetAccountConfig(BannerbearOperationConfig):
    operation: Literal["get_account"] = _operation("get_account", "Account")


class BannerbearListImagesConfig(BannerbearListConfig):
    operation: Literal["list_images"] = _operation("list_images", "Images")


class BannerbearGetImageConfig(BannerbearUIDConfig):
    operation: Literal["get_image"] = _operation("get_image", "Images")


class BannerbearCreateImageConfig(BannerbearImagePayload):
    operation: Literal["create_image"] = _operation("create_image", "Images")


class BannerbearListAnimationsConfig(BannerbearListConfig):
    operation: Literal["list_animations"] = _operation("list_animations", "Animations")


class BannerbearGetAnimationConfig(BannerbearUIDConfig):
    operation: Literal["get_animation"] = _operation("get_animation", "Animations")


class BannerbearCreateAnimationConfig(BannerbearOperationConfig):
    operation: Literal["create_animation"] = _operation("create_animation", "Animations")
    template: str = _template("animation_template")
    modifications: Json[dict[str, Any]] = Field(..., title="Modifications (JSON)", description='V5 object with objects and template overrides. Each object needs its id and type from Get Animation Template.', json_schema_extra={"ui:widget": "textarea"})
    formats: Json[list[Literal["mp4", "mov"]]] | None = Field(None, title="Formats (JSON)", description='Optional JSON array, e.g. ["mp4"]. Transparency forces MOV.', json_schema_extra={"ui:widget": "textarea"})
    metadata: str | None = Field(None, title="Metadata")

    @field_validator("formats", mode="before")
    @classmethod
    def encode_formats(cls, value):
        return json.dumps(value) if isinstance(value, list) else value

    @field_validator("modifications")
    @classmethod
    def validate_layers(cls, modifications):
        # The official V5 spec uses the full Layer union for animation overrides.
        # Its abbreviated quickstart omits required id/type; read these from the template.
        layers = modifications.get("objects", [])
        if not isinstance(layers, list) or any(
            not isinstance(layer, dict) or not layer.get("id") or not layer.get("type")
            for layer in layers
        ):
            raise ValueError("Animation objects need id and type from Get Animation Template")
        return modifications


class BannerbearListBatchesConfig(BannerbearListConfig):
    operation: Literal["list_batches"] = _operation("list_batches", "Batches")


class BannerbearGetBatchConfig(BannerbearUIDConfig):
    operation: Literal["get_batch"] = _operation("get_batch", "Batches")


class BannerbearCreateBatchConfig(BannerbearOperationConfig):
    operation: Literal["create_batch"] = _operation("create_batch", "Batches")
    type: Literal["images"] = Field("images", title="Batch Type")
    items: Json[list[dict[str, Any]]] = Field(..., title="Images (JSON)", description="JSON array of 1–100 V5 image payloads; each needs template and modifications.", json_schema_extra={"ui:widget": "textarea"})

    @field_validator("items")
    @classmethod
    def validate_items(cls, items):
        if not 1 <= len(items) <= 100:
            raise ValueError("Supply between 1 and 100 image payloads")
        # Normalize each payload too, so JSON text and expression-supplied values
        # use the same wire types as a single-image render.
        return [BannerbearImagePayload.model_validate(item).model_dump(mode="json", exclude_none=True)
                for item in items]


class BannerbearListImageTemplatesConfig(BannerbearListConfig):
    operation: Literal["list_image_templates"] = _operation("list_image_templates", "Image Templates")


class BannerbearGetImageTemplateConfig(BannerbearUIDConfig):
    operation: Literal["get_image_template"] = _operation("get_image_template", "Image Templates")
    uid: str = _template("image_template")


class BannerbearCreateImageTemplateConfig(BannerbearTemplateFields):
    operation: Literal["create_image_template"] = _operation("create_image_template", "Image Templates")
    name: str = Field(..., min_length=1, title="Name")


class BannerbearUpdateImageTemplateConfig(BannerbearTemplateFields, BannerbearUIDConfig):
    operation: Literal["update_image_template"] = _operation("update_image_template", "Image Templates")
    name: str | None = Field(None, min_length=1, title="Name")


class BannerbearDeleteImageTemplateConfig(BannerbearUIDConfig):
    operation: Literal["delete_image_template"] = _operation("delete_image_template", "Image Templates")


class BannerbearListAnimationTemplatesConfig(BannerbearListConfig):
    operation: Literal["list_animation_templates"] = _operation("list_animation_templates", "Animation Templates")


class BannerbearGetAnimationTemplateConfig(BannerbearUIDConfig):
    operation: Literal["get_animation_template"] = _operation("get_animation_template", "Animation Templates")
    uid: str = _template("animation_template")


class BannerbearCreateAnimationTemplateConfig(BannerbearTemplateFields):
    operation: Literal["create_animation_template"] = _operation("create_animation_template", "Animation Templates")
    name: str = Field(..., min_length=1, title="Name")
    frame_rate: Literal[24, 30, 60] | None = Field(None, title="Frame Rate")


class BannerbearUpdateAnimationTemplateConfig(BannerbearTemplateFields, BannerbearUIDConfig):
    operation: Literal["update_animation_template"] = _operation("update_animation_template", "Animation Templates")
    name: str | None = Field(None, min_length=1, title="Name")
    frame_rate: Literal[24, 30, 60] | None = Field(None, title="Frame Rate")


class BannerbearDeleteAnimationTemplateConfig(BannerbearUIDConfig):
    operation: Literal["delete_animation_template"] = _operation("delete_animation_template", "Animation Templates")


BannerbearConfig = Annotated[Union[
    BannerbearGetAccountConfig,
    BannerbearListImagesConfig,
    BannerbearGetImageConfig,
    BannerbearCreateImageConfig,
    BannerbearListAnimationsConfig,
    BannerbearGetAnimationConfig,
    BannerbearCreateAnimationConfig,
    BannerbearListBatchesConfig,
    BannerbearGetBatchConfig,
    BannerbearCreateBatchConfig,
    BannerbearListImageTemplatesConfig,
    BannerbearGetImageTemplateConfig,
    BannerbearCreateImageTemplateConfig,
    BannerbearUpdateImageTemplateConfig,
    BannerbearDeleteImageTemplateConfig,
    BannerbearListAnimationTemplatesConfig,
    BannerbearGetAnimationTemplateConfig,
    BannerbearCreateAnimationTemplateConfig,
    BannerbearUpdateAnimationTemplateConfig,
    BannerbearDeleteAnimationTemplateConfig,
], Field(discriminator="operation")]


class BannerbearNodeConfig(NodeConfig[BannerbearConfig, BannerbearAPIKeyCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/account"),
    "list_images": ("GET", "/images"),
    "get_image": ("GET", "/images/{uid}"),
    "create_image": ("POST", "/images"),
    "list_animations": ("GET", "/animations"),
    "get_animation": ("GET", "/animations/{uid}"),
    "create_animation": ("POST", "/animations"),
    "list_batches": ("GET", "/batches"),
    "get_batch": ("GET", "/batches/{uid}"),
    "create_batch": ("POST", "/batches"),
    "list_image_templates": ("GET", "/image_templates"),
    "get_image_template": ("GET", "/image_templates/{uid}"),
    "create_image_template": ("POST", "/image_templates"),
    "update_image_template": ("PATCH", "/image_templates/{uid}"),
    "delete_image_template": ("DELETE", "/image_templates/{uid}"),
    "list_animation_templates": ("GET", "/animation_templates"),
    "get_animation_template": ("GET", "/animation_templates/{uid}"),
    "create_animation_template": ("POST", "/animation_templates"),
    "update_animation_template": ("PATCH", "/animation_templates/{uid}"),
    "delete_animation_template": ("DELETE", "/animation_templates/{uid}"),
}


async def _request(api_key: str, operation: str, *, uid=None, params=None, body=None):
    method, path = ROUTES[operation]
    if "{uid}" in path:
        path = path.replace("{uid}", quote(str(uid), safe=""))
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, API_BASE + path,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}),
            )
        result = {"action": operation, "status_code": response.status_code,
                  "timing_ms": {"api_request": round((time.perf_counter() - start) * 1000, 2)}}
        if not response.is_success:
            # Preserve provider rejection text for connection evidence, redacting keys.
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            message = message if isinstance(message, str) and message else f"Bannerbear API returned HTTP {response.status_code}"
            return {**result, "status": "error", "error": message.replace(api_key, "[redacted]")}
        # Both DELETE endpoints document an empty body (200 for images, 204 for animations).
        if method == "DELETE" and not response.content:
            data = {"deleted": True}
        else:
            try:
                data = response.json()
            except ValueError:
                return {**result, "status": "error", "error": "Bannerbear returned invalid JSON"}
            expected = list if operation.startswith("list_") else dict
            if not isinstance(data, expected):
                return {**result, "status": "error", "error": "Bannerbear returned an unexpected response shape"}
        return {**result, "status": "success", "data": data}
    except httpx.TimeoutException:
        return {"status": "error", "action": operation, "status_code": 408, "error": "Bannerbear request timed out"}
    except httpx.RequestError:
        return {"status": "error", "action": operation, "error": "Could not reach the Bannerbear API"}


class BannerbearNode(WorkflowNode):
    integration_type = "automation-bannerbear"
    connection_evidence = ConnectionEvidence(
        field="image_template", noun="image templates", identity_operation="get_account",
        identity_keys=("workspace", "uid"),
    )
    edit_examples = [
        "Render a personalized marketing image from my template",
        "Generate an animation with different title text",
        "Batch-create campaign images and check their render status",
    ]

    @classmethod
    def get_config_model(cls):
        return BannerbearNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        operation = {"image_template": "list_image_templates", "animation_template": "list_animation_templates"}.get(field_name)
        if not operation or not credential_data:
            return {"options": []}
        page = max(1, int(page_token or 1))
        result = await _request(credential_data["api_key"], operation, params={"page": page})
        if result["status"] != "success":
            raise ValueError(result["error"])
        records = result["data"]
        options = [{"value": item["uid"], "label": item.get("name") or item["uid"]}
                   for item in records if isinstance(item, dict) and item.get("uid")]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        return {"options": options, "next_page_token": str(page + 1) if len(records) == 25 else None}

    async def execute(self, inputs):
        if not isinstance(self.config, BannerbearNodeConfig):
            raise ValueError("Valid Bannerbear configuration is required")
        if not self.config.credentials:
            raise ValueError("Connect a Bannerbear V5 API key in the credentials tab")
        config = self.config.config
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation", "uid"})
        method, _ = ROUTES[config.operation]
        return await _request(
            self.config.credentials.api_key, config.operation, uid=getattr(config, "uid", None),
            params=values if method == "GET" else None,
            body=values if method in {"POST", "PATCH"} else None,
        )
