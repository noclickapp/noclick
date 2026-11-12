"""BFL image generation, editing, task results and personal finetune utilities.

Wire models follow BFL OpenAPI 0.0.1 (sha256 ea458c661ef8b0e03d72ee6b29267451f5a04ae65f35e55ea8a87e53645ef670).
Each operation makes one documented request; generation returns a task, never a completed image.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.bfl.ai"
CREDENTIAL_TYPE = "bfl_api_key"


class BflAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        hide_input_in_errors=True,
        title="BFL API Key",
        json_schema_extra={
            "x-credential-url": "https://dashboard.bfl.ai",
            "x-credential-instructions": "Create an API key in your BFL dashboard, then paste it here. NoClick sends it in the x-key header to BFL. Reading your credit balance checks access without spending credits; generation and editing spend your BFL credits.",
        },
    )
    credential_type: Literal["bfl_api_key"] = Field(
        "bfl_api_key", json_schema_extra={"ui:hidden": True}
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
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the BFL API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BflGetCreditsConfig(_Input):
    """Get the user's credits."""

    operation: Literal["get_credits"] = Field(
        "get_credits", json_schema_extra={"ui:hidden": True}
    )


class BflListFinetunesConfig(_Input):
    """My Finetunes."""

    operation: Literal["list_finetunes"] = Field(
        "list_finetunes", json_schema_extra={"ui:hidden": True}
    )


class BflGetFinetuneDetailsConfig(_Input):
    """Finetune Details."""

    operation: Literal["get_finetune_details"] = Field(
        "get_finetune_details", json_schema_extra={"ui:hidden": True}
    )
    finetune_id: str = Field(..., max_length=256, min_length=1)


class BflDeleteFinetuneConfig(_Input):
    """Delete Finetune."""

    operation: Literal["delete_finetune"] = Field(
        "delete_finetune", json_schema_extra={"ui:hidden": True}
    )
    finetune_id: str = Field(
        ..., max_length=256, description="Name of the LoRA to delete.", min_length=1
    )


class BflGetResultConfig(_Input):
    """Get Result."""

    operation: Literal["get_result"] = Field(
        "get_result", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., max_length=256, min_length=1)
    polling_url: Optional[str] = Field(
        "",
        max_length=4096,
        description="Use the polling_url from the generation response for global or regional routing. The id must match this task. Omit only for a task whose endpoint is api.bfl.ai.",
    )


class BflGenerateFluxPro11Config(_Input):
    """Generate an image with FLUX1.1 [pro]."""

    operation: Literal["generate_flux_pro_11"] = Field(
        "generate_flux_pro_11", json_schema_extra={"ui:hidden": True}
    )
    prompt: Optional[str] = Field("", description="Text prompt for image generation.")
    image_prompt: Optional[str] = Field(
        None, description="Optional base64 encoded image to use with Flux Redux."
    )
    width: int = Field(
        1024,
        ge=256.0,
        le=1440.0,
        multiple_of=32.0,
        description="Width of the generated image in pixels. Must be a multiple of 32.",
    )
    height: int = Field(
        768,
        ge=256.0,
        le=1440.0,
        multiple_of=32.0,
        description="Height of the generated image in pixels. Must be a multiple of 32.",
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation.",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )


class BflGenerateFluxDevConfig(_Input):
    """Generate an image with FLUX.1 [dev]."""

    operation: Literal["generate_flux_dev"] = Field(
        "generate_flux_dev", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        "", max_length=32000, description="Text prompt for image generation."
    )
    image_prompt: Optional[str] = Field(
        None,
        description="Optional base64 encoded image to use as a prompt for generation.",
    )
    width: int = Field(
        1024,
        ge=256.0,
        le=1440.0,
        multiple_of=32.0,
        description="Width of the generated image in pixels. Must be a multiple of 32.",
    )
    height: int = Field(
        768,
        ge=256.0,
        le=1440.0,
        multiple_of=32.0,
        description="Height of the generated image in pixels. Must be a multiple of 32.",
    )
    steps: Optional[int] = Field(
        28,
        ge=1.0,
        le=50.0,
        description="Number of steps for the image generation process.",
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation.",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    guidance: Optional[float] = Field(
        3.0,
        ge=1.5,
        le=5.0,
        description="Guidance scale for image generation. High guidance scales improve prompt adherence at the cost of reduced realism.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )


class BflGenerateFluxUltraConfig(_Input):
    """Generate an image with FLUX1.1 [pro] ultra mode."""

    operation: Literal["generate_flux_ultra"] = Field(
        "generate_flux_ultra", json_schema_extra={"ui:hidden": True}
    )
    prompt: Optional[str] = Field(
        "", description="The prompt to use for image generation."
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation.",
    )
    seed: Optional[int] = Field(
        None,
        description="Optional seed for reproducibility. If not provided, a random seed will be used.",
    )
    aspect_ratio: str = Field(
        "16:9",
        max_length=32000,
        description="Aspect ratio of the image between 21:9 and 9:21",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    raw: bool = Field(
        False, description="Generate less processed, more natural-looking images"
    )
    image_prompt: Optional[str] = Field(
        None, description="Optional image to remix in base64 format"
    )
    image_prompt_strength: float = Field(
        0.1, ge=0.0, le=1.0, description="Blend between the prompt and the image prompt"
    )


class BflFillImageConfig(_Input):
    """Inpaint an image with FLUX.1 Fill [pro] using an input image and mask."""

    operation: Literal["fill_image"] = Field(
        "fill_image", json_schema_extra={"ui:hidden": True}
    )
    image: str = Field(
        ...,
        max_length=12000000,
        description="A Base64-encoded string representing the image you wish to modify. Can contain alpha mask if desired.",
    )
    mask: Optional[str] = Field(
        None,
        description="A Base64-encoded string representing a mask for the areas you want to modify in the image. The mask should be the same dimensions as the image and in black and white. Black areas (0%) indicate no modification, while white areas (100%) specify areas for inpainting. Optional if you provide an alpha mask in the original image. Validation: The endpoint verifies that the dimensions of the mask match the original image.",
    )
    prompt: Optional[str] = Field(
        "",
        description="The description of the changes you want to make. This text guides the inpainting process, allowing you to specify features, styles, or modifications for the masked area.",
    )
    steps: Optional[int] = Field(
        50,
        ge=15.0,
        le=50.0,
        description="Number of steps for the image generation process",
    )
    prompt_upsampling: Optional[bool] = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility")
    guidance: Optional[float] = Field(
        60,
        ge=1.5,
        le=100.0,
        description="Guidance strength for the image generation process",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )


class BflExpandImageConfig(_Input):
    """Expand an image with FLUX.1 Expand [pro] by adding pixels on any side."""

    operation: Literal["expand_image"] = Field(
        "expand_image", json_schema_extra={"ui:hidden": True}
    )
    image: str = Field(
        ...,
        max_length=12000000,
        description="A Base64-encoded string representing the image you wish to expand.",
    )
    top: Optional[int] = Field(
        0,
        ge=0.0,
        le=2048.0,
        description="Number of pixels to expand at the top of the image",
    )
    bottom: Optional[int] = Field(
        0,
        ge=0.0,
        le=2048.0,
        description="Number of pixels to expand at the bottom of the image",
    )
    left: Optional[int] = Field(
        0,
        ge=0.0,
        le=2048.0,
        description="Number of pixels to expand on the left side of the image",
    )
    right: Optional[int] = Field(
        0,
        ge=0.0,
        le=2048.0,
        description="Number of pixels to expand on the right side of the image",
    )
    prompt: Optional[str] = Field(
        "",
        description="The description of the changes you want to make. This text guides the expansion process, allowing you to specify features, styles, or modifications for the expanded areas.",
    )
    steps: Optional[int] = Field(
        50,
        ge=15.0,
        le=50.0,
        description="Number of steps for the image generation process",
    )
    prompt_upsampling: Optional[bool] = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility")
    guidance: Optional[float] = Field(
        60,
        ge=1.5,
        le=100.0,
        description="Guidance strength for the image generation process",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )


class BflGenerateFinetunedUltraConfig(_Input):
    """Generate an image with FLUX 1.1 [pro] finetune with ultra mode.."""

    operation: Literal["generate_finetuned_ultra"] = Field(
        "generate_finetuned_ultra", json_schema_extra={"ui:hidden": True}
    )
    finetune_id: str = Field(
        ...,
        max_length=256,
        description="Name of the LoRA to use. For LoRAs from other organizations (public or shared), use the format 'org-id/lora-name'.",
        min_length=1,
    )
    finetune_strength: float = Field(
        1.2,
        ge=0.0,
        le=2.0,
        description="Strength of the fine-tuned model. 0.0 means no influence, 1.0 means full influence. Allowed values up to 2.0",
    )
    prompt: Optional[str] = Field(
        "", description="The prompt to use for image generation."
    )
    seed: Optional[int] = Field(
        None,
        description="Optional seed for reproducibility. If not provided, a random seed will be used.",
    )
    aspect_ratio: str = Field(
        "16:9",
        max_length=32000,
        description="Aspect ratio of the image between 21:9 and 9:21",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "jpeg",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    image_prompt: Optional[str] = Field(
        None, description="Optional image to remix in base64 format"
    )
    image_prompt_strength: float = Field(
        0.1, ge=0.0, le=1.0, description="Blend between the prompt and the image prompt"
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation",
    )


class BflGenerateFlux2FlexConfig(_Input):
    """Generate or edit an image with FLUX.2 [flex]."""

    operation: Literal["generate_flux_2_flex"] = Field(
        "generate_flux_2_flex", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    prompt_upsampling: Optional[bool] = Field(
        True, description="Whether to use prompt upsampling."
    )
    input_image: Optional[str] = Field(None, description="Path to the input image.")
    input_image_2: Optional[str] = Field(
        None, description="Path to the second input image."
    )
    input_image_3: Optional[str] = Field(
        None, description="Path to the third input image."
    )
    input_image_4: Optional[str] = Field(
        None, description="Path to the fourth input image."
    )
    input_image_5: Optional[str] = Field(
        None, description="Path to the fifth input image."
    )
    input_image_6: Optional[str] = Field(
        None, description="Path to the sixth input image."
    )
    input_image_7: Optional[str] = Field(
        None, description="Path to the seventh input image."
    )
    input_image_8: Optional[str] = Field(
        None, description="Path to the eighth input image."
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    width: Optional[int] = Field(None, ge=64.0, description="Width of the image")
    height: Optional[int] = Field(None, ge=64.0, description="Height of the image")
    guidance: Optional[float] = Field(
        5.0,
        ge=1.5,
        le=10.0,
        description="Guidance scale for image generation. High guidance scales improve prompt adherence at the cost of reduced realism.",
    )
    steps: Optional[int] = Field(
        50,
        ge=1.0,
        le=50.0,
        description="Number of steps for image generation. Higher steps lead to more detailed and realistic images.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=7.0,
        description="Harm moderation tolerance from 0 to 7, with 0 the strictest. The route and organization determine the approved maximum and per-category ceilings. Unapproved levels return 422 with approved levels.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field("jpeg")


class BflGenerateFlux2Klein9BConfig(_Input):
    """Generate or edit an image with FLUX.2 [klein] 9B."""

    operation: Literal["generate_flux_2_klein_9b"] = Field(
        "generate_flux_2_klein_9b", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    input_image: Optional[str] = Field(None, description="Path to the input image.")
    input_image_2: Optional[str] = Field(
        None, description="Path to the second input image."
    )
    input_image_3: Optional[str] = Field(
        None, description="Path to the third input image."
    )
    input_image_4: Optional[str] = Field(
        None, description="Path to the fourth input image."
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    width: Optional[int] = Field(None, ge=64.0, description="Width of the image")
    height: Optional[int] = Field(None, ge=64.0, description="Height of the image")
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=7.0,
        description="Harm moderation tolerance from 0 to 7, with 0 the strictest. The route and organization determine the approved maximum and per-category ceilings. Unapproved levels return 422 with approved levels.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field("jpeg")


class BflGenerateFlux2Klein4BConfig(_Input):
    """Generate or edit an image with FLUX.2 [klein] 4B."""

    operation: Literal["generate_flux_2_klein_4b"] = Field(
        "generate_flux_2_klein_4b", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    input_image: Optional[str] = Field(None, description="Path to the input image.")
    input_image_2: Optional[str] = Field(
        None, description="Path to the second input image."
    )
    input_image_3: Optional[str] = Field(
        None, description="Path to the third input image."
    )
    input_image_4: Optional[str] = Field(
        None, description="Path to the fourth input image."
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    width: Optional[int] = Field(None, ge=64.0, description="Width of the image")
    height: Optional[int] = Field(None, ge=64.0, description="Height of the image")
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=7.0,
        description="Harm moderation tolerance from 0 to 7, with 0 the strictest. The route and organization determine the approved maximum and per-category ceilings. Unapproved levels return 422 with approved levels.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field("jpeg")


class BflGenerateFlux2MaxConfig(_Input):
    """Generate or edit an image with FLUX.2 [max]."""

    operation: Literal["generate_flux_2_max"] = Field(
        "generate_flux_2_max", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    disable_pup: bool = Field(
        False,
        description="Disable automatic prompt upsampling for this request. FLUX.2 [pro] and [max] apply prompt upsampling by default; set this to true to generate from your prompt exactly as written.",
    )
    input_image: Optional[str] = Field(None, description="Path to the input image.")
    input_image_2: Optional[str] = Field(
        None, description="Path to the second input image."
    )
    input_image_3: Optional[str] = Field(
        None, description="Path to the third input image."
    )
    input_image_4: Optional[str] = Field(
        None, description="Path to the fourth input image."
    )
    input_image_5: Optional[str] = Field(
        None, description="Path to the fifth input image."
    )
    input_image_6: Optional[str] = Field(
        None, description="Path to the sixth input image."
    )
    input_image_7: Optional[str] = Field(
        None, description="Path to the seventh input image."
    )
    input_image_8: Optional[str] = Field(
        None, description="Path to the eighth input image."
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    width: Optional[int] = Field(None, ge=64.0, description="Width of the image")
    height: Optional[int] = Field(None, ge=64.0, description="Height of the image")
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=7.0,
        description="Harm moderation tolerance from 0 to 7, with 0 the strictest. The route and organization determine the approved maximum and per-category ceilings. Unapproved levels return 422 with approved levels.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field("jpeg")


class BflGenerateFlux2ProConfig(_Input):
    """Generate or edit an image with FLUX.2 [pro]."""

    operation: Literal["generate_flux_2_pro"] = Field(
        "generate_flux_2_pro", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    disable_pup: bool = Field(
        False,
        description="Disable automatic prompt upsampling for this request. FLUX.2 [pro] and [max] apply prompt upsampling by default; set this to true to generate from your prompt exactly as written.",
    )
    input_image: Optional[str] = Field(None, description="Path to the input image.")
    input_image_2: Optional[str] = Field(
        None, description="Path to the second input image."
    )
    input_image_3: Optional[str] = Field(
        None, description="Path to the third input image."
    )
    input_image_4: Optional[str] = Field(
        None, description="Path to the fourth input image."
    )
    input_image_5: Optional[str] = Field(
        None, description="Path to the fifth input image."
    )
    input_image_6: Optional[str] = Field(
        None, description="Path to the sixth input image."
    )
    input_image_7: Optional[str] = Field(
        None, description="Path to the seventh input image."
    )
    input_image_8: Optional[str] = Field(
        None, description="Path to the eighth input image."
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    width: Optional[int] = Field(None, ge=64.0, description="Width of the image")
    height: Optional[int] = Field(None, ge=64.0, description="Height of the image")
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=7.0,
        description="Harm moderation tolerance from 0 to 7, with 0 the strictest. The route and organization determine the approved maximum and per-category ceilings. Unapproved levels return 422 with approved levels.",
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field("jpeg")


class BflGenerateKontextMaxConfig(_Input):
    """Edit or create an image with FLUX.1 Kontext [max]."""

    operation: Literal["generate_kontext_max"] = Field(
        "generate_kontext_max", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    input_image: Optional[str] = Field(
        None, description="Base64 encoded image or URL to use with Kontext."
    )
    input_image_2: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    input_image_3: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    input_image_4: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    aspect_ratio: Optional[str] = Field(
        None, description="Aspect ratio of the image between 21:9 and 9:21"
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "png",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )


class BflGenerateKontextProConfig(_Input):
    """Edit or create an image with FLUX.1 Kontext [pro]."""

    operation: Literal["generate_kontext_pro"] = Field(
        "generate_kontext_pro", json_schema_extra={"ui:hidden": True}
    )
    prompt: str = Field(
        ..., max_length=32000, description="Text prompt for image generation."
    )
    input_image: Optional[str] = Field(
        None, description="Base64 encoded image or URL to use with Kontext."
    )
    input_image_2: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    input_image_3: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    input_image_4: Optional[str] = Field(
        None,
        description="Base64 encoded image or URL to use with Kontext. *Experimental Multiref*",
    )
    seed: Optional[int] = Field(None, description="Optional seed for reproducibility.")
    aspect_ratio: Optional[str] = Field(
        None, description="Aspect ratio of the image between 21:9 and 9:21"
    )
    output_format: Optional[Literal["jpeg", "png", "webp"]] = Field(
        "png",
        description="Output format for the generated image. Can be 'jpeg', 'png', or 'webp'.",
    )
    prompt_upsampling: bool = Field(
        False,
        description="Whether to perform upsampling on the prompt. If active, automatically modifies the prompt for more creative generation.",
    )
    safety_tolerance: int = Field(
        2,
        ge=0.0,
        le=6.0,
        description="Tolerance level for input and output moderation. Between 0 and 6, 0 being most strict, 6 being least strict.",
    )


# BFL's own MCP server: agents get its tools through a person's BFL sign-in.
BflMcpCredential = mcp_credential("bfl", "https://mcp.bfl.ai", app="BFL")
BflCredential = Union[BflAPIKeyCredential, BflMcpCredential]


BflConfig = Annotated[
    Union[
        BflGetCreditsConfig,
        BflListFinetunesConfig,
        BflGetFinetuneDetailsConfig,
        BflDeleteFinetuneConfig,
        BflGetResultConfig,
        BflGenerateFluxPro11Config,
        BflGenerateFluxDevConfig,
        BflGenerateFluxUltraConfig,
        BflFillImageConfig,
        BflExpandImageConfig,
        BflGenerateFinetunedUltraConfig,
        BflGenerateFlux2FlexConfig,
        BflGenerateFlux2Klein9BConfig,
        BflGenerateFlux2Klein4BConfig,
        BflGenerateFlux2MaxConfig,
        BflGenerateFlux2ProConfig,
        BflGenerateKontextMaxConfig,
        BflGenerateKontextProConfig,
    ],
    Field(discriminator="operation"),
]


class BflFullConfig(NodeConfig[BflConfig, BflCredential]):
    pass


ROUTES = {
    "get_credits": ("GET", "/v1/credits"),
    "list_finetunes": ("GET", "/v1/my_finetunes"),
    "get_finetune_details": ("GET", "/v1/finetune_details"),
    "delete_finetune": ("POST", "/v1/delete_finetune"),
    "get_result": ("GET", "/v1/get_result"),
    "generate_flux_pro_11": ("POST", "/v1/flux-pro-1.1"),
    "generate_flux_dev": ("POST", "/v1/flux-dev"),
    "generate_flux_ultra": ("POST", "/v1/flux-pro-1.1-ultra"),
    "fill_image": ("POST", "/v1/flux-pro-1.0-fill"),
    "expand_image": ("POST", "/v1/flux-pro-1.0-expand"),
    "generate_finetuned_ultra": ("POST", "/v1/flux-pro-1.1-ultra-finetuned"),
    "generate_flux_2_flex": ("POST", "/v1/flux-2-flex"),
    "generate_flux_2_klein_9b": ("POST", "/v1/flux-2-klein-9b"),
    "generate_flux_2_klein_4b": ("POST", "/v1/flux-2-klein-4b"),
    "generate_flux_2_max": ("POST", "/v1/flux-2-max"),
    "generate_flux_2_pro": ("POST", "/v1/flux-2-pro"),
    "generate_kontext_max": ("POST", "/v1/flux-kontext-max"),
    "generate_kontext_pro": ("POST", "/v1/flux-kontext-pro"),
}


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)


class _Credits(_Response):
    credits: float


class _Finetunes(_Response):
    finetunes: list[Any]


class _Details(_Response):
    finetune_details: dict[str, Any]


class _Deleted(_Response):
    status: str
    message: str
    deleted_finetune_id: str
    timestamp: str


class _Task(_Response):
    id: str = Field(min_length=1)
    polling_url: str = Field(min_length=1)
    cost: Optional[float] = None
    input_mp: Optional[float] = None
    output_mp: Optional[float] = None


class _Result(_Response):
    id: str
    status: Literal[
        "Task not found",
        "Pending",
        "Reasoning",
        "Generating",
        "Request Moderated",
        "Content Moderated",
        "No Card Generated",
        "Ready",
        "Error",
    ]
    result: Any = None
    progress: Optional[float] = None
    details: Optional[dict[str, Any]] = None
    preview: Optional[dict[str, Any]] = None
    cost: Optional[float] = None


def _polling_url(value, task_id):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port
        or not re.fullmatch(r"api(?:\.[a-z0-9-]+)*\.bfl\.ai", parsed.hostname or "")
        or parsed.path != "/v1/get_result"
        or parsed.fragment
        or parse_qs(parsed.query, keep_blank_values=True) != {"id": [task_id]}
    ):
        raise ValueError("Use the BFL polling_url for this exact task")
    return value


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class BflNode(WorkflowNode):
    integration_type = "automation-bfl"
    credential_provider_labels = {"bfl": "BFL Account"}
    connection_evidence = ConnectionEvidence(
        noun="BFL credit balance", operation="get_credits", proves="reachability"
    )

    @classmethod
    def get_config_model(cls):
        return BflFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a BFL API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        params = op.model_dump(
            exclude={"operation", "polling_url"}, exclude_none=True, exclude_unset=True
        )
        url = BASE + path
        if op.operation == "get_result" and op.polling_url:
            url = _polling_url(op.polling_url, op.id)
            params = None  # returned URL already carries exactly this task id
        try:
            async with guarded_async_client(
                timeout=60, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"x-key": key, "Accept": "application/json"},
                    **({"params": params} if method == "GET" else {"json": params}),
                )
        except httpx.HTTPError:
            raise ValueError(
                "BFL request could not be confirmed; inspect tasks before retrying a generation"
            ) from None
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for connection evidence, without leaking the key.
            message = _redact(response.text[:2000], key)
            raise ValueError(f"BFL HTTP {response.status_code}: {message}")
        if (
            len(response.content) > 16_000_000
            or "json" not in response.headers.get("content-type", "").lower()
        ):
            raise ValueError(
                "BFL returned an unexpected response; inspect tasks before retrying a write"
            )
        try:
            raw = response.json()
            model = {
                "get_credits": _Credits,
                "list_finetunes": _Finetunes,
                "get_finetune_details": _Details,
                "delete_finetune": _Deleted,
                "get_result": _Result,
            }.get(op.operation, _Task)
            data = model.model_validate(raw).model_dump(exclude_unset=True)
            # Treat returned polling URLs as data; validate the destination only before polling.
            if model is _Result and data["id"] != op.id:
                raise ValueError("Task identity differs")
            if model is _Deleted and data["deleted_finetune_id"] != op.finetune_id:
                raise ValueError("Finetune identity differs")
        except Exception:
            raise ValueError(
                "BFL response could not be verified; inspect tasks before retrying a write"
            ) from None
        output = {
            "status": "success",
            "operation": op.operation,
            "data": _redact(data, key),
        }
        await self.emit(output)
        return output
