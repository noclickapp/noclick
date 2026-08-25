"""Image generation config — DALL-E, Imagen, Gemini native image models, etc."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields


_GEMINI_IMAGE_MODELS = [
    "gemini-2.0-flash-preview-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
]
_IMAGEN_MODELS = ["imagen-3", "imagen-4"]
_GPT_IMAGE_SHOW_IF = {"field": "model", "containsAll": ["gpt", "image"]}
_IMAGE_ASPECT_RATIOS = [
    "1:1",
    "3:4",
    "4:3",
    "9:16",
    "16:9",
    "2:3",
    "3:2",
    "4:5",
    "5:4",
    "21:9",
]
_IMAGE_ASPECT_RATIO_NAMES = [
    "1:1 (Square)",
    "3:4 (Portrait)",
    "4:3 (Landscape)",
    "9:16 (Vertical)",
    "16:9 (Widescreen)",
    "2:3",
    "3:2",
    "4:5 (Instagram)",
    "5:4",
    "21:9 (Ultrawide)",
]


class ImageConfig(BaseAgentFields):
    """Configuration for image generation models."""
    model_type: Literal["image"] = Field(
        default="image",
        title="Model Type",
        json_schema_extra={"ui:hidden": True},
    )
    model: str = Field(
        default="openrouter/openai/dall-e-3",
        title="Model",
        description="Image generation model",
        json_schema_extra={
            "x-queryable-enum": "models",
            "x-enum-hint": (
                "LiteLLM identifier for an image-generation model. Fuzzy input is "
                "auto-resolved to the closest registered id."
            ),
        },
    )

    # ── OpenRouter GPT Image Settings ────────────────────────────────────────
    # GPT image models are routed through OpenRouter Chat Completions. Prompting
    # for a ratio is not reliable; OpenRouter expects these as image_config.
    openrouter_image_aspect_ratio: str = Field(
        default="1:1",
        title="Aspect Ratio",
        json_schema_extra={
            "enum": _IMAGE_ASPECT_RATIOS,
            "enumNames": _IMAGE_ASPECT_RATIO_NAMES,
            "x-enum-searchable": True,
            "ui:category": "OpenRouter Image Settings",
            "ui:help": "Controls the generated image shape. Use this field instead of relying on prompt text like 'make it 16:9'.",
            "ui:show-if": _GPT_IMAGE_SHOW_IF,
        },
    )
    openrouter_image_size: str = Field(
        default="1K",
        title="Image Size",
        json_schema_extra={
            "enum": ["1K", "2K"],
            "enumNames": [
                "1K (standard)",
                "2K (higher resolution)",
            ],
            "x-enum-searchable": True,
            "ui:category": "OpenRouter Image Settings",
            "ui:show-if": _GPT_IMAGE_SHOW_IF,
        },
    )
    openrouter_seed: str = Field(
        default="",
        title="Seed",
        json_schema_extra={
            "ui:category": "OpenRouter Image Settings",
            "ui:help": "Optional integer seed for more reproducible GPT image generations when supported by the selected OpenRouter model.",
            "ui:show-if": _GPT_IMAGE_SHOW_IF,
        },
    )

    # ── Google / Gemini Image Settings ───────────────────────────────────────
    # Shown for Gemini native image models (via OpenRouter) and Imagen models
    # (direct Gemini API with generateImages endpoint).
    gemini_aspect_ratio: str = Field(
        default="1:1",
        title="Aspect Ratio",
        json_schema_extra={
            "enum": _IMAGE_ASPECT_RATIOS,
            "enumNames": _IMAGE_ASPECT_RATIO_NAMES,
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {
                "field": "model",
                "containsAny": _GEMINI_IMAGE_MODELS + _IMAGEN_MODELS,
            },
        },
    )
    gemini_image_size: str = Field(
        default="1K",
        title="Image Size",
        json_schema_extra={
            "enum": ["0.5K", "1K", "2K", "4K"],
            "enumNames": [
                "0.5K (~512px, Flash only)",
                "1K (~1024px)",
                "2K (~2048px)",
                "4K (~4096px, Pro only)",
            ],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {"field": "model", "containsAny": _GEMINI_IMAGE_MODELS},
        },
    )
    gemini_reference_image_url: str = Field(
        default="",
        title="Reference Images",
        json_schema_extra={
            "ui:category": "Image Settings",
            "ui:help": "Optional images for the model to edit, use as style references, or build upon. Supports JPEG, PNG, WebP. Add multiple images for multi-image prompts.",
            "ui:widget": "gemini_multi_image_upload",
            "ui:show-if": {
                "anyOf": [
                    {"field": "model", "containsAny": _GEMINI_IMAGE_MODELS},
                    {"field": "model", "containsAll": ["gpt", "image"]},
                ]
            },
        },
    )
    gemini_num_images: str = Field(
        default="1",
        title="Number of Images",
        json_schema_extra={
            "enum": ["1", "2", "3", "4"],
            "enumNames": ["1", "2", "3", "4"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    # Imagen-only fields (direct Gemini API via generateImages endpoint)
    imagen_negative_prompt: str = Field(
        default="",
        title="Negative Prompt",
        json_schema_extra={
            "ui:widget": "textarea",
            "ui:category": "Google Image Settings",
            "ui:help": "Describe what to exclude from the generated image.",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_guidance_scale: str = Field(
        default="",
        title="Guidance Scale",
        json_schema_extra={
            "ui:category": "Google Image Settings",
            "ui:help": "Controls how closely the image follows the prompt (0–30). Higher = more faithful to prompt.",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_seed: str = Field(
        default="",
        title="Seed",
        json_schema_extra={
            "ui:category": "Google Image Settings",
            "ui:help": "Seed for reproducible results. Requires 'Add Watermark' to be disabled.",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_person_generation: str = Field(
        default="allow_adult",
        title="Person Generation",
        json_schema_extra={
            "enum": ["dont_allow", "allow_adult", "allow_all"],
            "enumNames": ["Don't Allow", "Allow Adults Only", "Allow All Ages"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:help": "Controls whether people can appear in generated images. 'Allow All' blocked in some regions.",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_safety_setting: str = Field(
        default="block_medium_and_above",
        title="Safety Filter",
        json_schema_extra={
            "enum": ["block_low_and_above", "block_medium_and_above", "block_only_high"],
            "enumNames": ["Strict (block low+)", "Standard (block medium+)", "Permissive (block high only)"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_enhance_prompt: str = Field(
        default="true",
        title="Enhance Prompt",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (recommended)", "No"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:help": "Automatically rewrites your prompt for better image quality.",
            "ui:show-if": {"field": "model", "containsAny": ["imagen-4"]},
        }
    )
    imagen_add_watermark: str = Field(
        default="true",
        title="Add SynthID Watermark",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No (required for seed to work)"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
    imagen_output_mime_type: str = Field(
        default="image/png",
        title="Output Format",
        json_schema_extra={
            "enum": ["image/png", "image/jpeg"],
            "enumNames": ["PNG", "JPEG"],
            "x-enum-searchable": True,
            "ui:category": "Google Image Settings",
            "ui:show-if": {"field": "model", "containsAny": _IMAGEN_MODELS},
        }
    )
