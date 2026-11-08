"""Dynamic Mockups API v1: account catalogs, templates, renders and AI jobs.

Each operation makes one request to the provider's published endpoint. Returned
asset URLs and asynchronous job state remain provider data; no download or poll
loop runs implicitly. API submissions may consume the account's credits.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.dynamicmockups.com/api/v1"
CREDENTIAL_TYPE = "dynamic_mockups_api_key"


class DynamicMockupsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Dynamic Mockups API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.dynamicmockups.com/",
            "x-credential-instructions": "Paste your Dynamic Mockups API key from the app's API settings. NoClick sends it in the x-api-key header. Rendering, PSD uploads and AI submissions can use your account credits.",
        },
    )
    credential_type: Literal["dynamic_mockups_api_key"] = Field(
        "dynamic_mockups_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_api_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CreateAiMockupConfigProductDecorationsItemImprintSize(_Input):
    width: float | None = Field(None)
    height: float | None = Field(None)
    unit: str | None = Field(None)


class CreateAiMockupConfigProductDecorationsItem(_Input):
    location: str | None = Field(
        None,
        description="Decoration area to target, from `GET /mock-anything/products/{uuid}`. When omitted, the product's default decoration area is used.",
    )
    position_id: str | None = Field(
        None,
        description="Exact stored decoration position identifier from `decorations[].position_id` in the product detail response. Use this to distinguish provider-specific positions that share a canonical location.",
    )
    source: str | None = Field(
        None,
        description="Enabled provider source from the selected product-detail decoration's `sources` list. Matching trims surrounding whitespace and is case-insensitive; the canonical stored source is forwarded. When omitted, the position's default source is used.",
    )
    decoration_method: str | None = Field(
        None,
        description="Decoration method to apply (e.g. `dtg`, `screen_print`, `embroidery`, `dtf`, `heat_transfer`). The value is forwarded as sent. When the selected position lists methods and none of them matches (case-insensitive; each run of spaces and/or hyphens reads as one `_`; common synonyms such as `screen_printing` = `screen_print` accepted), the request still proceeds and the response carries a `decoration_method_not_supported` warning for that `location`; the source and sizing are not changed. No warning is given for a disabled position or one whose data lists no methods. See product details for valid positions.",
    )
    imprint_size: CreateAiMockupConfigProductDecorationsItemImprintSize | None = Field(
        None, description="Desired physical imprint size."
    )


class CreateAiMockupConfigProduct(_Input):
    uuid: str | None = Field(
        None,
        description="UUID of a POD product (obtained via `GET /mock-anything/products`) to anchor the AI generation around a specific product type.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    selected_size: str | None = Field(
        None,
        max_length=50,
        description="Optional product size. Must exactly match one of the product's `sizes[].label` values (from `GET /mock-anything/products/{uuid}`). A matched size is taken into account by the generation where the product's category and size data support it (real-world scale and/or output aspect). A value that matches none of the product's sizes is rejected with a 400 error naming the product's valid size labels; when the product cannot be resolved, the value is accepted without effect. Only meaningful together with `product.uuid`.",
    )
    color_name: str | None = Field(
        None,
        max_length=255,
        description="Optional exact product color name from `GET /mock-anything/products/{uuid}`. The value is case-sensitive and must match one of `colors[].name`. Product detail must be available to validate this selector.",
    )
    decorations: list[CreateAiMockupConfigProductDecorationsItem] | None = Field(
        None,
        description="Optional list of decoration areas to place on the product. Each item can target a canonical `location` or an exact `position_id`, and can select an exact enabled `source`, all from `GET /mock-anything/products/{uuid}`. When omitted, the product's default decoration area and source are used.\n",
    )


class CreateAiMockupConfigCollectionsItem(_Input):
    uuid: str | None = Field(
        None,
        description="UUID of an existing collection.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    name: str | None = Field(
        None,
        max_length=255,
        description="Name of a new collection to create and attach.",
    )


class UploadPsdConfigMockupTemplate(_Input):
    create_after_upload: bool | None = Field(
        None, description="Whether to create a mockup template after the PSD upload."
    )
    collections: list[str] | None = Field(
        None,
        description="Optional list of collection UUIDs to associate with the mockup template.",
    )
    catalog_uuid: str | None = Field(
        None,
        description="Optional catalog UUID to add the created mockup to. If not provided, the mockup will be added to the default catalog.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class CreateBulkRenderConfigExportOptions(_Input):
    image_format: Literal["webp", "jpg", "png"] | None = Field(None)
    image_size: int | None = Field(None)
    mode: Literal["view", "download"] | None = Field(None)


class CreateRenderConfigExportOptions(_Input):
    image_format: Literal["jpg", "png", "webp"] | None = Field(
        None, description="The format of the exported image."
    )
    image_size: int | None = Field(
        None, description="The size in pixels of the exported image."
    )
    mode: Literal["view", "download"] | None = Field(
        None,
        description="Determines whether the exported image should be viewed in the browser or downloaded.",
    )


class CreateRenderConfigSmartObjectsItemAssetSize(_Input):
    width: int | None = Field(None, description="The width of the asset in pixels.")
    height: int | None = Field(None, description="The height of the asset pixels.")


class CreateRenderConfigSmartObjectsItemAssetPosition(_Input):
    top: int | None = Field(None, description="The top position of the asset.")
    left: int | None = Field(None, description="The left position of the asset.")


class CreateRenderConfigSmartObjectsItemAsset(_Input):
    url: str | None = Field(None, description="URL to the asset image.")
    fit: Literal["stretch", "contain", "cover"] | None = Field(
        None, description="How the asset fits within the designated area."
    )
    size: CreateRenderConfigSmartObjectsItemAssetSize | None = Field(None)
    position: CreateRenderConfigSmartObjectsItemAssetPosition | None = Field(None)
    rotate: float | None = Field(
        None, description="The rotation angle of the provided asset."
    )


class CreateRenderConfigSmartObjectsItemPattern(_Input):
    enabled: bool | None = Field(
        None, description="Whether the asset is used as a repeating pattern."
    )
    scale_percent: float | None = Field(
        None, description="Scale of the pattern relative to the original asset size."
    )


class CreateRenderConfigSmartObjectsItemAdjustmentLayers(_Input):
    brightness: int | None = Field(
        None, description="Brightness adjustment (from -150 to 150)."
    )
    contrast: int | None = Field(
        None, description="Contrast adjustment (from -100 to 100)."
    )
    opacity: int | None = Field(None, description="Opacity adjustment (from 0 to 100).")
    saturation: int | None = Field(
        None, description="Saturation adjustment (from -100 to 100)."
    )
    vibrance: int | None = Field(
        None, description="Vibrance adjustment (from -100 to 100)."
    )
    blur: int | None = Field(None, description="Blur adjustment (from 0 to 100).")


class CreateRenderConfigSmartObjectsItemDecorationMethodOptions(_Input):
    material: Literal["metal", "leather", "wood"] | None = Field(
        None, description="Simulated material finish for engrave and deboss methods."
    )
    desaturation: float | None = Field(
        None,
        description="laser_engrave_surface: how much of the artwork color is removed (0 to 1).",
    )
    burn_darkness: float | None = Field(
        None,
        description="laser_engrave_surface: darkness of the burned engraving (0 to 1).",
    )
    wall_width: float | None = Field(
        None,
        description="laser_engrave_deep: width of the engraved channel walls, in pixels.",
    )
    groove_darkness: float | None = Field(
        None,
        description="laser_engrave_deep: shadow darkness inside the engraved grooves (0 to 1).",
    )
    depth: float | None = Field(
        None, description="deboss: depth of the pressed-in impression (0 to 1)."
    )
    shadow_falloff: float | None = Field(
        None, description="deboss: softness of the impression's shadow edge, in pixels."
    )
    shadow_darkness: float | None = Field(
        None, description="deboss: darkness of the impression's shadow (0 to 1)."
    )
    highlight_brightness: float | None = Field(
        None, description="deboss: brightness of the raised highlight."
    )
    center_darkening: float | None = Field(
        None,
        description="deboss: darkening toward the center of the impression (0 to 1).",
    )


class CreateRenderConfigSmartObjectsItemDecorationMethod(_Input):
    method: Literal[
        "universal",
        "screen_print",
        "dtg",
        "uv_print",
        "laser_engrave_surface",
        "laser_engrave_deep",
        "deboss",
    ] = Field(
        ...,
        description="The decoration method to apply. universal = flat print that leaves artwork colors unchanged (your chosen blending_mode still applies); screen_print, dtg and uv_print are print finishes that simulate how ink sits on the material and shift artwork colors accordingly (dtg simulates ink soaked into fabric: expect desaturation and strong darkening on dark garments); laser_engrave_surface and laser_engrave_deep are engravings (the artwork acts as a stencil and its colors are replaced by the engraved material); deboss is a pressed-in impression.",
    )
    options: CreateRenderConfigSmartObjectsItemDecorationMethodOptions | None = Field(
        None,
        description="Optional fine-tuning for the selected method. Only laser_engrave_surface, laser_engrave_deep and deboss read options; any value you omit uses a sensible default.",
    )


class CreateRenderConfigSmartObjectsItem(_Input):
    uuid: str | None = Field(
        None,
        description="The UUID of the smart object.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    asset: CreateRenderConfigSmartObjectsItemAsset | None = Field(None)
    pattern: CreateRenderConfigSmartObjectsItemPattern | None = Field(
        None, description="Configuration for using the asset as a repeating pattern."
    )
    color: str | None = Field(
        None, description="Color overlay for the smart object in hex code."
    )
    blending_mode: Literal[
        "NORMAL",
        "DISSOLVE",
        "DARKEN",
        "MULTIPLY",
        "COLOR_BURN",
        "LINEAR_BURN",
        "DARKER_COLOR",
        "LIGHTEN",
        "SCREEN",
        "COLOR_DODGE",
        "LINEAR_DODGE",
        "LIGHTER_COLOR",
        "OVERLAY",
        "SOFT_LIGHT",
        "HARD_LIGHT",
        "VIVID_LIGHT",
        "LINEAR_LIGHT",
        "PIN_LIGHT",
        "HARD_MIX",
        "DIFFERENCE",
        "EXCLUSION",
        "SUBTRACT",
        "DIVIDE",
        "HUE",
        "SATURATION",
        "COLOR",
        "LUMINOSITY",
    ] | None = Field(None, description="Blending mode applied to the smart object.")
    adjustment_layers: CreateRenderConfigSmartObjectsItemAdjustmentLayers | None = (
        Field(
            None, description="Optional adjustment layers applied to the smart object."
        )
    )
    print_area_preset_uuid: str | None = Field(
        None,
        description="UUID of the print area preset to automatically position provided design asset.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    decoration_method: CreateRenderConfigSmartObjectsItemDecorationMethod | None = Field(
        None,
        description="Render-time decoration method (print finish) applied to this smart object's artwork. Only affects MockAnything templates; classic PSD mockups ignore it. Every method except universal simulates a physical print or engraving process and intentionally alters the artwork's colors (ink absorption, desaturation, fabric show-through), most visibly on dark garments. To reproduce your artwork's original colors, set method to universal or omit this field (omitting keeps the template's default finish, which is universal unless the template was saved with a different one); scene lighting and shading still apply.",
    )


class CreateRenderConfigTextLayersItem(_Input):
    uuid: str | None = Field(
        None,
        description="The UUID of the text layer.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    text: str | None = Field(None, description="The text content for the text layer.")
    font_family: str | None = Field(None, description="The font family of the text.")
    font_size: float | None = Field(
        None, description="The font size for the text in pixels."
    )
    font_color: str | None = Field(
        None, description="The color of the text in hex code."
    )


class CreateBatchRenderConfigExportOptions(_Input):
    image_format: Literal["jpg", "png", "webp"] | None = Field(
        None, description="The format of the exported image."
    )
    image_size: int | None = Field(
        None, description="The size in pixels of the exported image."
    )
    mode: Literal["view", "download"] | None = Field(
        None,
        description="Determines whether the exported image should be viewed in the browser or downloaded.",
    )


class CreateBatchRenderConfigRendersItemSmartObjectsItemAssetSize(_Input):
    width: int | None = Field(None, description="The width of the asset in pixels.")
    height: int | None = Field(None, description="The height of the asset in pixels.")


class CreateBatchRenderConfigRendersItemSmartObjectsItemAsset(_Input):
    url: str | None = Field(None, description="URL to the asset image.")
    fit: Literal["stretch", "contain", "cover"] | None = Field(
        None, description="How the asset fits within the designated area."
    )
    size: CreateBatchRenderConfigRendersItemSmartObjectsItemAssetSize | None = Field(
        None
    )
    position: CreateRenderConfigSmartObjectsItemAssetPosition | None = Field(None)
    rotate: float | None = Field(
        None, description="The rotation angle of the provided asset."
    )


class CreateBatchRenderConfigRendersItemSmartObjectsItem(_Input):
    uuid: str | None = Field(
        None,
        description="The UUID of the smart object.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    asset: CreateBatchRenderConfigRendersItemSmartObjectsItemAsset | None = Field(None)
    pattern: CreateRenderConfigSmartObjectsItemPattern | None = Field(
        None, description="Configuration for using the asset as a repeating pattern."
    )
    color: str | None = Field(
        None, description="Color overlay for the smart object in hex code."
    )
    blending_mode: Literal[
        "NORMAL",
        "DISSOLVE",
        "DARKEN",
        "MULTIPLY",
        "COLOR_BURN",
        "LINEAR_BURN",
        "DARKER_COLOR",
        "LIGHTEN",
        "SCREEN",
        "COLOR_DODGE",
        "LINEAR_DODGE",
        "LIGHTER_COLOR",
        "OVERLAY",
        "SOFT_LIGHT",
        "HARD_LIGHT",
        "VIVID_LIGHT",
        "LINEAR_LIGHT",
        "PIN_LIGHT",
        "HARD_MIX",
        "DIFFERENCE",
        "EXCLUSION",
        "SUBTRACT",
        "DIVIDE",
        "HUE",
        "SATURATION",
        "COLOR",
        "LUMINOSITY",
    ] | None = Field(None, description="Blending mode applied to the smart object.")
    adjustment_layers: CreateRenderConfigSmartObjectsItemAdjustmentLayers | None = (
        Field(
            None, description="Optional adjustment layers applied to the smart object."
        )
    )
    print_area_preset_uuid: str | None = Field(
        None,
        description="UUID of the print area preset to automatically position provided design asset.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    decoration_method: CreateRenderConfigSmartObjectsItemDecorationMethod | None = Field(
        None,
        description="Render-time decoration method (print finish) applied to this smart object's artwork. Only affects MockAnything templates; classic PSD mockups ignore it. Every method except universal simulates a physical print or engraving process and intentionally alters the artwork's colors (ink absorption, desaturation, fabric show-through), most visibly on dark garments. To reproduce your artwork's original colors, set method to universal or omit this field (omitting keeps the template's default finish, which is universal unless the template was saved with a different one); scene lighting and shading still apply.",
    )


class CreateBatchRenderConfigRendersItem(_Input):
    export_label: str | None = Field(
        None, description="A label for the exported image."
    )
    mockup_uuid: str = Field(
        ...,
        description="The UUID of the mockup template.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    smart_objects: list[CreateBatchRenderConfigRendersItemSmartObjectsItem] = Field(
        ..., description="List of smart objects inside the chosen mockup."
    )
    text_layers: list[CreateRenderConfigTextLayersItem] | None = Field(
        None, description="List of text layers for the chosen mockup."
    )


class ExportPrintFilesConfigExportOptions(_Input):
    image_format: Literal["jpg", "png", "webp"] | None = Field(
        None, description="The format of the exported image."
    )
    image_size: int | None = Field(
        None, description="The size in pixels of the exported image."
    )
    mode: Literal["view", "download"] | None = Field(
        None,
        description="Determines whether the exported image should be viewed in the browser or downloaded.",
    )
    image_dpi: int | None = Field(
        None, description="Dots per inch for the exported print file."
    )


class ExportPrintFilesConfigSmartObjectsItem(_Input):
    uuid: str | None = Field(
        None,
        description="The UUID of the smart object.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    asset: CreateRenderConfigSmartObjectsItemAsset | None = Field(None)
    pattern: CreateRenderConfigSmartObjectsItemPattern | None = Field(
        None, description="Configuration for using the asset as a repeating pattern."
    )
    color: str | None = Field(
        None, description="Color overlay for the smart object in hex code."
    )
    blending_mode: Literal[
        "NORMAL",
        "DISSOLVE",
        "DARKEN",
        "MULTIPLY",
        "COLOR_BURN",
        "LINEAR_BURN",
        "DARKER_COLOR",
        "LIGHTEN",
        "SCREEN",
        "COLOR_DODGE",
        "LINEAR_DODGE",
        "LIGHTER_COLOR",
        "OVERLAY",
        "SOFT_LIGHT",
        "HARD_LIGHT",
        "VIVID_LIGHT",
        "LINEAR_LIGHT",
        "PIN_LIGHT",
        "HARD_MIX",
        "DIFFERENCE",
        "EXCLUSION",
        "SUBTRACT",
        "DIVIDE",
        "HUE",
        "SATURATION",
        "COLOR",
        "LUMINOSITY",
    ] | None = Field(None, description="Blending mode applied to the smart object.")
    adjustment_layers: CreateRenderConfigSmartObjectsItemAdjustmentLayers | None = (
        Field(
            None, description="Optional adjustment layers applied to the smart object."
        )
    )
    print_area_preset_uuid: str | None = Field(
        None,
        description="UUID of the print area preset to automatically position provided design asset.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ListCatalogsConfig(_Input):
    """Get Catalogs."""

    operation: Literal["list_catalogs"] = Field(
        "list_catalogs", json_schema_extra={"ui:hidden": True}
    )


class CreateCatalogConfig(_Input):
    """Create Catalog."""

    operation: Literal["create_catalog"] = Field(
        "create_catalog", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="The name of the custom catalog to create.",
    )


class ListCollectionsConfig(_Input):
    """Get Collections."""

    operation: Literal["list_collections"] = Field(
        "list_collections", json_schema_extra={"ui:hidden": True}
    )
    catalog_uuid: str | None = Field(
        None,
        description="Optional UUID of the catalog to filter collections by.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    include_all_catalogs: bool | None = Field(
        None,
        description="Optional parameter to include collections from all catalogs. If false or omitted, only collections from the default catalog are returned. Set to true to fetch from all catalogs.",
    )


class CreateCollectionConfig(_Input):
    """Create Collection."""

    operation: Literal["create_collection"] = Field(
        "create_collection", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., description="The name of the collection to create.")
    catalog_uuid: str | None = Field(
        None,
        description="Optional UUID of the catalog to place this collection in. If not provided, uses the default catalog.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ListMockupsConfig(_Input):
    """Get Mockups."""

    operation: Literal["list_mockups"] = Field(
        "list_mockups", json_schema_extra={"ui:hidden": True}
    )
    catalog_uuid: str | None = Field(
        None,
        description="Optional parameter to filter mockups by catalog UUID.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    collection_uuid: str | None = Field(
        None,
        description="Optional parameter to filter mockups by collection UUID.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    include_all_catalogs: bool | None = Field(
        None,
        description="Optional parameter to include mockups from all catalogs. If false or omitted, only mockups from the default catalog are returned. Set to true to fetch from all catalogs.",
    )
    name: str | None = Field(
        None, description="Optional parameter to filter mockups by name."
    )


class GetMockupConfig(_Input):
    """Get Specific Mockup."""

    operation: Literal["get_mockup"] = Field(
        "get_mockup", json_schema_extra={"ui:hidden": True}
    )
    uuid: str = Field(
        ...,
        description="The UUID of the mockup to retrieve.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class CreateAiMockupConfig(_Input):
    """Create MockAnything AI Mockup."""

    operation: Literal["create_ai_mockup"] = Field(
        "create_ai_mockup", json_schema_extra={"ui:hidden": True}
    )
    prompt: str | None = Field(
        None,
        description="Text prompt used to AI-generate the mockup image. Required unless `image_url` or `image_file` is provided.",
    )
    image_url: str | None = Field(
        None,
        description="URL of an existing image to use as the mockup image. Required unless `prompt` or `image_file` is provided.",
    )
    enhance_prompt: bool | None = Field(
        None,
        description="Whether to run prompt enhancement before generation. Only applies to the `prompt` flow.",
    )
    product: CreateAiMockupConfigProduct | None = Field(
        None, description="Optional product context used to ground the AI generation."
    )
    model: Literal[
        "nano_banana_2",
        "nano_banana_lite",
        "seedream_4_0",
        "seedream_4_5",
        "gpt_image_2",
    ] | None = Field(
        None,
        description="AI model used for generation. Only applies to the `prompt` flow. Required when `style` is provided. When omitted, generations default to `nano_banana_2`, which runs on Nano Banana 2.1 (Google's `gemini-nano-banana-2.1`) since October 2026. `nano_banana_lite` and `gpt_image_2` apply to product-backed generations (a `product.uuid` present).",
    )
    style: str | None = Field(
        None,
        description="Visual style applied to the AI generation (e.g. `polaroid-etsy`, `ugc`, `fashion`). Use `GET /mock-anything/styles?model={model}` to list the styles available for a given model; not every model supports every style. When `style` is provided, `model` is required.",
    )
    name: str | None = Field(
        None,
        max_length=255,
        description="Optional mockup name shown in the dashboard and returned in the `mockup.name` field.",
    )
    collections: list[CreateAiMockupConfigCollectionsItem] | None = Field(
        None,
        description="Optional collections to attach the mockup to. Each item is either an existing collection (by `uuid`) or a new collection to create (by `name`). Exactly one of `uuid` or `name` must be provided per item.",
    )
    catalog_uuid: str | None = Field(
        None,
        description="Optional UUID of the catalog the mockup belongs to. Defaults to the workspace's default catalog.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_generation(self):
        if not self.prompt and not self.image_url:
            raise ValueError("Provide a prompt or an image URL")
        if self.style and not self.model:
            raise ValueError("Select the model that supports this style")
        for collection in self.collections or []:
            if bool(collection.uuid) == bool(collection.name):
                raise ValueError("Each collection needs exactly one UUID or name")
        return self


class GetAiMockupStatusConfig(_Input):
    """Get MockAnything AI Mockup Status."""

    operation: Literal["get_ai_mockup_status"] = Field(
        "get_ai_mockup_status", json_schema_extra={"ui:hidden": True}
    )
    taskId: str = Field(
        ...,
        description="The `task_id` returned from `POST /mock-anything/create`.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ListBlankProductsConfig(_Input):
    """List Entitled Blank Products."""

    operation: Literal["list_blank_products"] = Field(
        "list_blank_products", json_schema_extra={"ui:hidden": True}
    )
    page: int | None = Field(None, ge=1)
    per_page: int | None = Field(None, ge=1, le=100)


class SearchAiProductsConfig(_Input):
    """Search POD Products."""

    operation: Literal["search_ai_products"] = Field(
        "search_ai_products", json_schema_extra={"ui:hidden": True}
    )
    query: str = Field(
        ..., min_length=1, description="Search term matched against POD product names."
    )


class GetAiProductConfig(_Input):
    """Get POD Product Details."""

    operation: Literal["get_ai_product"] = Field(
        "get_ai_product", json_schema_extra={"ui:hidden": True}
    )
    uuid: str = Field(
        ...,
        description="UUID of the POD product (from `GET /mock-anything/products`).",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ListAiStylesConfig(_Input):
    """List Available Styles."""

    operation: Literal["list_ai_styles"] = Field(
        "list_ai_styles", json_schema_extra={"ui:hidden": True}
    )
    model: Literal[
        "nano_banana_2",
        "nano_banana_lite",
        "seedream_4_0",
        "seedream_4_5",
        "gpt_image_2",
    ] | None = Field(
        None,
        description="Optional model filter. When provided, only styles available for that model are returned.",
    )


class CreateMotionMockupConfig(_Input):
    """Submit a MotionMockups AI Request."""

    operation: Literal["create_motion_mockup"] = Field(
        "create_motion_mockup", json_schema_extra={"ui:hidden": True}
    )
    start_image_url: str = Field(
        ...,
        max_length=2000,
        description="Publicly accessible URL of the source image to animate.",
    )
    model: Literal["kling_v2.6", "kling_v3_pro"] | None = Field(
        None,
        description="The MotionMockups AI model to use. Defaults to the standard model when omitted.",
    )
    prompt: str | None = Field(
        None,
        max_length=2500,
        description="Optional text prompt describing the desired video. When omitted, a prompt is generated from the image.",
    )
    negative_prompt: str | None = Field(
        None,
        max_length=1000,
        description="Optional description of what to avoid in the generated video.",
    )
    duration: int | None = Field(
        None,
        description="Video length in seconds. Allowed values depend on the selected model (see `GET /motion-mockups/models`). Defaults to the model's default duration.",
    )
    aspect_ratio: str | None = Field(
        None,
        description="Output aspect ratio. Only supported by some models, with a model-specific set of allowed values (see `GET /motion-mockups/models`).",
    )
    generate_audio: bool | None = Field(
        None,
        description="Whether to also generate audio. Increases the credit cost by a model-specific multiplier.",
    )
    skip_discovery: bool | None = Field(
        None,
        description="When `true` and no `prompt` is provided, skip image auto-prompting and use a neutral default prompt.",
    )


class GetMotionStatusConfig(_Input):
    """Get MotionMockups AI Request Status."""

    operation: Literal["get_motion_status"] = Field(
        "get_motion_status", json_schema_extra={"ui:hidden": True}
    )
    requestId: str = Field(
        ...,
        description="The `request_id` returned by the submit endpoint.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ListMotionModelsConfig(_Input):
    """List MotionMockups AI Models."""

    operation: Literal["list_motion_models"] = Field(
        "list_motion_models", json_schema_extra={"ui:hidden": True}
    )


class UploadPsdConfig(_Input):
    """Upload a PSD file."""

    operation: Literal["upload_psd"] = Field(
        "upload_psd", json_schema_extra={"ui:hidden": True}
    )
    psd_file_url: str = Field(..., description="The URL to the PSD file.")
    psd_name: str | None = Field(None, description="An optional name for the PSD file.")
    psd_category_id: int | None = Field(
        None, description="An optional category ID for the PSD file."
    )
    mockup_template: UploadPsdConfigMockupTemplate | None = Field(
        None,
        description="Optional settings for creating a mockup template after the PSD upload.",
    )


class DeletePsdConfig(_Input):
    """Delete a PSD file."""

    operation: Literal["delete_psd"] = Field(
        "delete_psd", json_schema_extra={"ui:hidden": True}
    )
    psd_uuid: str = Field(
        ...,
        description="The UUID of the PSD file to delete.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    delete_related_mockups: bool | None = Field(
        None, description="Whether to delete all mockups related to this PSD file."
    )


class ListProductsConfig(_Input):
    """Retrieve a list of products."""

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    is_published: bool | None = Field(
        None, description="Filter by publication status (true for published only)."
    )


class CreateBulkRenderConfig(_Input):
    """Create Bulk Renders Based on Mockup Collection."""

    operation: Literal["create_bulk_render"] = Field(
        "create_bulk_render", json_schema_extra={"ui:hidden": True}
    )
    collection_uuid: str = Field(
        ...,
        description="The unique identifier of collection created in My Templates section: https://app.dynamicmockups.com/my-templates\n",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    artworks: dict[str, Any] | None = Field(None)
    colors: dict[str, Any] | None = Field(
        None, description="Key-value map of color inputs using hex codes"
    )
    export_label: str | None = Field(None)
    export_options: CreateBulkRenderConfigExportOptions | None = Field(
        None,
        description="Optional settings used to control the format, size, and behavior of the exported images.",
    )


class CreateRenderConfig(_Input):
    """Create a Mockup Render."""

    operation: Literal["create_render"] = Field(
        "create_render", json_schema_extra={"ui:hidden": True}
    )
    mockup_uuid: str = Field(
        ...,
        description="The UUID of the mockup template.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    export_label: str | None = Field(
        None, description="A label for the exported image."
    )
    export_options: CreateRenderConfigExportOptions | None = Field(None)
    smart_objects: list[CreateRenderConfigSmartObjectsItem] = Field(
        ..., description="List of smart objects inside a chosen mockup."
    )
    text_layers: list[CreateRenderConfigTextLayersItem] | None = Field(
        None, description="List of text layers for the chosen mockup."
    )


class CreateBatchRenderConfig(_Input):
    """Render Multiple Mockups."""

    operation: Literal["create_batch_render"] = Field(
        "create_batch_render", json_schema_extra={"ui:hidden": True}
    )
    export_options: CreateBatchRenderConfigExportOptions | None = Field(
        None, description="Export options applied to all renders in the batch."
    )
    renders: list[CreateBatchRenderConfigRendersItem] = Field(
        ..., description="Array of render requests to process in the batch."
    )


class ExportPrintFilesConfig(_Input):
    """Export Print Files."""

    operation: Literal["export_print_files"] = Field(
        "export_print_files", json_schema_extra={"ui:hidden": True}
    )
    mockup_uuid: str = Field(
        ...,
        description="The UUID of the mockup template.",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    export_label: str | None = Field(
        None, description="A label for the exported image."
    )
    export_options: ExportPrintFilesConfigExportOptions | None = Field(None)
    smart_objects: list[ExportPrintFilesConfigSmartObjectsItem] = Field(
        ..., description="List of smart objects inside a chosen mockup."
    )
    text_layers: list[CreateRenderConfigTextLayersItem] | None = Field(
        None, description="List of text layers for the chosen mockup."
    )


DynamicMockupsConfig = Annotated[
    Union[
        ListCatalogsConfig,
        CreateCatalogConfig,
        ListCollectionsConfig,
        CreateCollectionConfig,
        ListMockupsConfig,
        GetMockupConfig,
        CreateAiMockupConfig,
        GetAiMockupStatusConfig,
        ListBlankProductsConfig,
        SearchAiProductsConfig,
        GetAiProductConfig,
        ListAiStylesConfig,
        CreateMotionMockupConfig,
        GetMotionStatusConfig,
        ListMotionModelsConfig,
        UploadPsdConfig,
        DeletePsdConfig,
        ListProductsConfig,
        CreateBulkRenderConfig,
        CreateRenderConfig,
        CreateBatchRenderConfig,
        ExportPrintFilesConfig,
    ],
    Field(discriminator="operation"),
]

# One published operation per entry: method, path, query fields, path fields.
ROUTES = {
    "list_catalogs": ("GET", "/catalogs", [], []),
    "create_catalog": ("POST", "/catalogs", [], []),
    "list_collections": (
        "GET",
        "/collections",
        ["catalog_uuid", "include_all_catalogs"],
        [],
    ),
    "create_collection": ("POST", "/collections", [], []),
    "list_mockups": (
        "GET",
        "/mockups",
        ["catalog_uuid", "collection_uuid", "include_all_catalogs", "name"],
        [],
    ),
    "get_mockup": ("GET", "/mockup/{uuid}", [], ["uuid"]),
    "create_ai_mockup": ("POST", "/mock-anything/create", [], []),
    "get_ai_mockup_status": ("GET", "/mock-anything/status/{taskId}", [], ["taskId"]),
    "list_blank_products": (
        "GET",
        "/mock-anything/blank-products",
        ["page", "per_page"],
        [],
    ),
    "search_ai_products": ("GET", "/mock-anything/products", ["query"], []),
    "get_ai_product": ("GET", "/mock-anything/products/{uuid}", [], ["uuid"]),
    "list_ai_styles": ("GET", "/mock-anything/styles", ["model"], []),
    "create_motion_mockup": ("POST", "/motion-mockups/submit", [], []),
    "get_motion_status": (
        "GET",
        "/motion-mockups/status/{requestId}",
        [],
        ["requestId"],
    ),
    "list_motion_models": ("GET", "/motion-mockups/models", [], []),
    "upload_psd": ("POST", "/psd/upload", [], []),
    "delete_psd": ("POST", "/psd/delete", [], []),
    "list_products": ("GET", "/products", ["is_published"], []),
    "create_bulk_render": ("POST", "/renders/bulk", [], []),
    "create_render": ("POST", "/renders", [], []),
    "create_batch_render": ("POST", "/renders/batch", [], []),
    "export_print_files": ("POST", "/renders/print-files", [], []),
}


class DynamicMockupsFullConfig(
    NodeConfig[DynamicMockupsConfig, DynamicMockupsAPIKeyCredential]
):
    pass


class DynamicMockupsNode(WorkflowNode):
    integration_type = "automation-dynamic-mockups"
    connection_evidence = ConnectionEvidence(
        noun="catalogs", operation="list_catalogs", label_keys=("name", "uuid")
    )

    @classmethod
    def get_config_model(cls):
        return DynamicMockupsFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Dynamic Mockups API key")
        config = self.config.config
        method, path, query_fields, path_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in path_fields:
            path = path.replace(
                "{" + field + "}", quote(str(values.pop(field)), safe="")
            )
        params = {key: values.pop(key) for key in query_fields if key in values}
        params = {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in params.items()
        }
        headers = {
            "x-api-key": self.config.credentials.api_key,
            "Accept": "application/json",
        }
        try:
            async with guarded_async_client(
                timeout=120, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    headers=headers,
                    params=params,
                    **({"json": values} if method != "GET" else {}),
                )
        except httpx.RequestError:
            raise ValueError(
                "Dynamic Mockups request could not be confirmed; inspect submitted jobs before retrying a write"
            ) from None
        if not 200 <= response.status_code < 300:
            # Never expose request headers, provider HTML or exception objects.
            message = "Dynamic Mockups request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(
                    payload.get("message"), str
                ):
                    message = payload["message"][:2000].replace(
                        self.config.credentials.api_key, "[redacted]"
                    )
            except ValueError:
                pass
            output = {
                "status": "error",
                "success": False,
                "http_status": response.status_code,
                "message": message,
            }
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError(
                    "Dynamic Mockups returned an unexpected JSON response; inspect before retrying a write"
                ) from None
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("success"), bool)
                or "data" not in payload
            ):
                raise ValueError(
                    "Dynamic Mockups response envelope could not be verified"
                )
            output = {
                **payload,
                "status": "success" if payload["success"] else "error",
                "http_status": response.status_code,
            }
        await self.emit(output)
        return output
