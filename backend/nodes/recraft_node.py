"""Recraft's published external API, using pasted bearer API tokens.

Contract: https://external.api.recraft.ai/doc/spec/external-api.yaml (0.0.1).
Each operation sends exactly one request. Image results use expiring provider
URLs; this node never downloads an input URL or returns base64 image bodies.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://external.api.recraft.ai"
CREDENTIAL_TYPE = "recraft_api_token"

TransformModel = Literal['recraftv2', 'recraftv2_raster', 'recraftv2_vector', 'recraftv3', 'recraftv3_raster', 'recraftv3_vector', 'recraftv4', 'recraftv4_raster', 'recraftv4_vector', 'recraftv4_pro', 'recraftv4_pro_raster', 'recraftv4_pro_vector', 'recraftv4_1', 'recraftv4_1_raster', 'recraftv4_1_vector', 'recraftv4_1_pro', 'recraftv4_1_pro_raster', 'recraftv4_1_pro_vector', 'recraftv4_1_utility', 'recraftv4_1_utility_raster', 'recraftv4_1_utility_vector', 'recraftv4_1_utility_pro', 'recraftv4_1_utility_pro_raster', 'recraftv4_1_utility_pro_vector', 'recraftv4_styles', 'recraftv4_styles_raster', 'recraftv4_styles_vector', 'recraftv4_styles_pro', 'recraftv4_styles_pro_raster', 'recraftv4_styles_pro_vector']

ImageSize = Literal['1024x1024', '1365x1024', '1024x1365', '1536x1024', '1024x1536', '1820x1024', '1024x1820', '1024x2048', '2048x1024', '1434x1024', '1024x1434', '1024x1280', '1280x1024', '1024x1707', '1707x1024', '1216x896', '896x1216', '1280x832', '832x1280', '1152x896', '896x1152', '1280x896', '896x1280', '832x1344', '768x1344', '1344x768', '768x1536', '1536x768', '2048x2048', '2432x1792', '1792x2432', '2560x1664', '1664x2560', '2304x1792', '1792x2304', '2560x1792', '1792x2560', '1664x2688', '1536x2688', '2688x1536', '1536x3072', '3072x1536', '1:1', '2:1', '1:2', '3:2', '2:3', '4:3', '3:4', '5:4', '4:5', '6:10', '14:10', '10:14', '16:9', '9:16']

ImageStyle = Literal['any', 'digital_illustration', 'icon', 'realistic_image', 'vector_illustration', 'logo_raster']

class RecraftAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Recraft API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.recraft.ai/app/api/api-keys",
            "x-credential-instructions": "Create an API token in Recraft's API portal and paste it here. API billing is separate from the Studio subscription. NoClick reads your current account to verify this token. Image and style creation use your Recraft API credits.",
        })
    credential_type: Literal["recraft_api_token"] = Field("recraft_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or any(ord(c) > 126 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class ImageColor(_Input):
    rgb: list[Annotated[int, Field(ge=0, le=255)]] = Field(..., min_length=3, max_length=3)
    std: list[float] | None = None
    weight: float | None = Field(None, ge=0)


class UserControls(_Input):
    artistic_level: int | None = Field(None, ge=0, le=5)
    background_color: ImageColor | None = None
    colors: list[ImageColor] | None = None
    no_text: bool | None = None


class TextLayoutItem(_Input):
    text: str
    bbox: list[list[float]] = Field(..., min_length=4, max_length=4)


def _image_url(value):
    # Recraft fetches the image; NoClick never fetches or forwards credentials to it.
    if not isinstance(value, str) or not value.startswith(("https://", "data:image/")):
        raise ValueError("Use an HTTPS image URL or an image data URL")
    return value


class _ResultOptions(_Input):
    image_format: Literal["webp", "png"] | None = None
    zdr: bool | None = Field(None, description="Zero data retention. A requested URL still uploads the output so it can be served.")


class _Generation(_ResultOptions):
    prompt: str = Field(..., min_length=1, max_length=10000, json_schema_extra={"ui:widget": "textarea"})
    model: TransformModel | None = Field(None, description="Choose a model compatible with this operation; V3 supports inpaint, outpaint and background editing.")
    n: int | None = Field(None, ge=1, le=6)
    negative_prompt: str | None = None
    random_seed: int | None = Field(None, ge=0, le=4294967295)
    style: str | None = None
    style_id: UUID | None = Field(None, description="A custom style ID returned by Create Style or List Styles.")
    style_match: Literal["regular", "precise", "flexible"] | None = None
    controls: UserControls | None = None
    text_layout: list[TextLayoutItem] | None = None


class _Generate(_Generation):
    size: ImageSize | None = None
    upscale: Literal["upscale4mp", "upscale16mp"] | None = None
    style_reference_urls: list[str] | None = Field(None, min_length=1, max_length=10)

    @field_validator("style_reference_urls")
    @classmethod
    def images(cls, value):
        return [_image_url(v) for v in value] if value is not None else value


class _ImageInput(_ResultOptions):
    image_url: str = Field(..., description="HTTPS URL or image data URL. Recraft reads the image directly.")

    @field_validator("image_url")
    @classmethod
    def image(cls, value):
        return _image_url(value)


class _Transform(_Generation, _ImageInput):
    pass


class _MaskedTransform(_Transform):
    mask_url: str = Field(..., description="Mask of the same size: white pixels change, black pixels stay.")

    @field_validator("mask_url")
    @classmethod
    def mask(cls, value):
        return _image_url(value)


class _Process(_ImageInput):
    upscale: Literal["upscale4mp", "upscale16mp"] | None = None


class GetCurrentUser(_Input):
    """Read the current account's ID, name, email and remaining API credits."""
    operation: Literal["get_current_user"] = "get_current_user"


class ListStyles(_Input):
    """List the custom styles available to this account."""
    operation: Literal["list_styles"] = "list_styles"


class ListBasicStyles(_Input):
    """List Recraft's built-in styles and their compatible models."""
    operation: Literal["list_basic_styles"] = "list_basic_styles"


class GetStyle(_Input):
    """Read one custom style by its UUID."""
    operation: Literal["get_style"] = "get_style"
    style_id: UUID


class DeleteStyle(_Input):
    """Delete a custom style by its UUID."""
    operation: Literal["delete_style"] = "delete_style"
    style_id: UUID


class CreateStyle(_Input):
    """Create a reusable style from reference images; consumes Recraft credits."""
    operation: Literal["create_style"] = "create_style"
    image_urls: list[str] = Field(..., min_length=1, max_length=10)
    style: ImageStyle | None = None

    @field_validator("image_urls")
    @classmethod
    def images(cls, value):
        return [_image_url(v) for v in value]


class GenerateImage(_Generate):
    """Generate images from a prompt; consumes Recraft credits."""
    operation: Literal["generate_image"] = "generate_image"


class GenerateRaster(_Generate):
    """Generate raster images from a prompt; consumes Recraft credits."""
    operation: Literal["generate_raster"] = "generate_raster"


class GenerateVector(_Generate):
    """Generate SVG images from a prompt; consumes Recraft credits."""
    operation: Literal["generate_vector"] = "generate_vector"


class ImageToImage(_Transform):
    """Transform an image with a prompt; consumes Recraft credits."""
    operation: Literal["image_to_image"] = "image_to_image"
    strength: float = Field(..., ge=0, le=1, description="1 is least similar to the original.")


class Inpaint(_MaskedTransform):
    """Regenerate masked image content from a prompt; consumes credits."""
    operation: Literal["inpaint"] = "inpaint"


class GenerateBackground(_MaskedTransform):
    """Generate a background in the masked area; consumes credits."""
    operation: Literal["generate_background"] = "generate_background"


class ReplaceBackground(_Transform):
    """Replace the background from a prompt; consumes credits."""
    operation: Literal["replace_background"] = "replace_background"


class Outpaint(_Transform):
    """Extend image borders using a prompt; consumes credits."""
    operation: Literal["outpaint"] = "outpaint"
    size: ImageSize | None = None
    expand_left: int | None = Field(None, ge=0, le=4294967295)
    expand_right: int | None = Field(None, ge=0, le=4294967295)
    expand_top: int | None = Field(None, ge=0, le=4294967295)
    expand_bottom: int | None = Field(None, ge=0, le=4294967295)
    zoom_out_percentage: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def expansion(self):
        expands = any(getattr(self, field) for field in ("expand_left", "expand_right", "expand_top", "expand_bottom"))
        if self.size and expands:
            raise ValueError("Choose size or pixel expansion, not both")
        if not self.size and not expands and not self.zoom_out_percentage:
            raise ValueError("Choose a size, pixel expansion or zoom out percentage")
        return self


class VariateImage(_ImageInput):
    """Generate variations without a prompt; consumes credits."""
    operation: Literal["variate_image"] = "variate_image"
    size: ImageSize
    model: TransformModel | None = None
    n: int | None = Field(None, ge=1, le=6)
    random_seed: int | None = Field(None, ge=0, le=4294967295)


class RemoveBackground(_Process):
    """Remove the image background; consumes credits."""
    operation: Literal["remove_background"] = "remove_background"


class CrispUpscale(_Process):
    """Upscale an image while preserving its content; consumes credits."""
    operation: Literal["crisp_upscale"] = "crisp_upscale"


class CreativeUpscale(_Process):
    """Upscale and regenerate fine details; consumes credits."""
    operation: Literal["creative_upscale"] = "creative_upscale"


class EnhanceImage(_ImageInput):
    """Enhance textures and details; consumes credits."""
    operation: Literal["enhance_image"] = "enhance_image"
    refinement: Literal["subtle", "moderate"] | None = None


class EraseRegion(_ImageInput):
    """Erase masked objects from an image; consumes credits."""
    operation: Literal["erase_region"] = "erase_region"
    mask_url: str

    @field_validator("mask_url")
    @classmethod
    def mask(cls, value):
        return _image_url(value)


class VectorizeImage(_Process):
    """Convert a raster image to SVG; consumes credits."""
    operation: Literal["vectorize_image"] = "vectorize_image"
    color_reduction: Literal["on", "off"] | None = None
    limit_num_shapes: Literal["on", "off"] | None = None
    max_num_colors: int | None = Field(None, ge=0, le=4294967295)
    max_num_shapes: int | None = Field(None, ge=0, le=4294967295)
    return_gradients: Literal["on", "off"] | None = None
    shape_stacking: Literal["cut_out", "hierarchical"] | None = None
    small_shape_filter: Literal["on", "off"] | None = None
    strict_color_palette: list[list[int]] | None = None
    svg_compression: Literal["on", "off"] | None = None


RecraftConfig = Annotated[Union[
    GetCurrentUser, ListStyles, ListBasicStyles, GetStyle, DeleteStyle, CreateStyle,
    GenerateImage, GenerateRaster, GenerateVector, ImageToImage, Inpaint,
    GenerateBackground, ReplaceBackground, Outpaint, VariateImage,
    RemoveBackground, CrispUpscale, CreativeUpscale, EnhanceImage, EraseRegion,
    VectorizeImage,
], Field(discriminator="operation")]


class RecraftFullConfig(NodeConfig[RecraftConfig, RecraftAPITokenCredential]):
    pass


# One native operation -> one published contract operation. No implicit writes,
# preflight requests, retries, resource readbacks or composite operations.
ROUTES = {
    "get_current_user": ("GET", "/v1/users/me"),
    "list_styles": ("GET", "/v1/styles"),
    "list_basic_styles": ("GET", "/v1/styles/basic"),
    "get_style": ("GET", "/v1/styles/{style_id}"),
    "delete_style": ("DELETE", "/v1/styles/{style_id}"),
    "create_style": ("POST", "/v1/styles"),
    "generate_image": ("POST", "/v1/images/generations"),
    "generate_raster": ("POST", "/v1/images/generations/raster"),
    "generate_vector": ("POST", "/v1/images/generations/vector"),
    "image_to_image": ("POST", "/v1/images/imageToImage"),
    "inpaint": ("POST", "/v1/images/inpaint"),
    "generate_background": ("POST", "/v1/images/generateBackground"),
    "replace_background": ("POST", "/v1/images/replaceBackground"),
    "outpaint": ("POST", "/v1/images/outpaint"),
    "variate_image": ("POST", "/v1/images/variateImage"),
    "remove_background": ("POST", "/v1/images/removeBackground"),
    "crisp_upscale": ("POST", "/v1/images/crispUpscale"),
    "creative_upscale": ("POST", "/v1/images/creativeUpscale"),
    "enhance_image": ("POST", "/v1/images/enhance"),
    "erase_region": ("POST", "/v1/images/eraseRegion"),
    "vectorize_image": ("POST", "/v1/images/vectorize"),
}


class _Image(BaseModel):
    # Ignore a provider's optional b64_json field: results are always requested as URLs.
    image_id: UUID
    url: str | None = None
    revised_prompt: str | None = None


class _Generated(BaseModel):
    created: int
    credits: int
    data: list[_Image]
    style_id: UUID | None = None


class _Processed(BaseModel):
    created: int
    credits: int
    image: _Image


class _User(BaseModel):
    id: UUID
    credits: int
    name: str | None = None
    email: str | None = None


class _Style(BaseModel):
    id: UUID
    style: ImageStyle
    creation_time: str
    is_private: bool


class _CreatedStyle(_Style):
    credits: int


class _BasicStyle(BaseModel):
    style_id: UUID
    style: str
    model: TransformModel


class _Styles(BaseModel):
    styles: list[_Style]


class _BasicStyles(BaseModel):
    styles: list[_BasicStyle]


def _guard_credential(data):
    raw = data.get("credentials")
    if isinstance(raw, dict) and raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
        raise ValueError("Attach a Recraft API token credential")


class RecraftNode(WorkflowNode):
    integration_type = "automation-recraft"
    connection_evidence = ConnectionEvidence(
        noun="Recraft account", identity_operation="get_current_user",
        identity_keys=("name", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return RecraftFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not isinstance(self.config, RecraftFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Recraft API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[config.operation]
        body = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{style_id}" in path:
            path = path.format(style_id=body.pop("style_id"))
        if path.startswith("/v1/images/"):
            body["response_format"] = "url"
        async with guarded_async_client(timeout=180, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                **({"json": body} if method == "POST" else {}))
        if response.status_code != 200:
            # Preserve provider diagnostics for the connect seam, without echoing secrets.
            message = response.text.replace(token, "[redacted]")[:1000]
            raise ValueError(f"Recraft API {response.status_code}: {message}")
        try:
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("Expected a JSON object")
            if config.operation == "get_current_user":
                model = _User
            elif config.operation == "list_styles":
                model = _Styles
            elif config.operation == "list_basic_styles":
                model = _BasicStyles
            elif config.operation == "get_style":
                model = _Style
            elif config.operation == "create_style":
                model = _CreatedStyle
            elif config.operation == "delete_style":
                return {"status": "success", "data": raw}
            else:
                model = _Generated if config.operation in {"generate_image", "generate_raster", "generate_vector", "image_to_image", "inpaint", "generate_background", "replace_background", "outpaint", "variate_image"} else _Processed
            result = model.model_validate(raw).model_dump(mode="json", exclude_none=True)
        except Exception:
            raise ValueError("Recraft returned an unexpected response shape") from None
        return {"status": "success", "data": result}
