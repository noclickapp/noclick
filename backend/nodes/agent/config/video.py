"""Video generation config — OpenRouter video models (Veo, Kling, Wan, …)."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields
from utils.media_generation import DEFAULT_VIDEO_MODEL


# The handler applies these settings to Veo models only (handlers/video.py).
_VEO_SHOW_IF = {"field": "model", "contains": "veo"}


class VideoConfig(BaseAgentFields):
    """Configuration for video generation models, run through OpenRouter."""
    model_type: Literal["video"] = Field(
        default="video",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default=DEFAULT_VIDEO_MODEL,
        title="Model",
        description="Video generation model",
        json_schema_extra={
            "x-queryable-enum": "models",
            "x-enum-hint": (
                "OpenRouter video model id (e.g. google/veo-3.1-fast). Fuzzy input is "
                "auto-resolved to the closest registered id."
            ),
        },
    )
    veo_aspect_ratio: str = Field(
        default="16:9",
        title="Aspect Ratio",
        json_schema_extra={
            "enum": ["16:9", "9:16"],
            "enumNames": ["16:9 (Landscape)", "9:16 (Portrait)"],
            "x-enum-searchable": True,
            "ui:category": "Video Settings",
            "ui:show-if": _VEO_SHOW_IF,
        }
    )
    veo_duration_seconds: str = Field(
        default="8",
        title="Duration (seconds)",
        json_schema_extra={
            "enum": ["4", "6", "8"],
            "enumNames": ["4s", "6s", "8s"],
            "x-enum-searchable": True,
            "ui:category": "Video Settings",
            "ui:show-if": _VEO_SHOW_IF,
        }
    )
    veo_resolution: str = Field(
        default="720p",
        title="Resolution",
        json_schema_extra={
            "enum": ["720p", "1080p"],
            "enumNames": ["720p (HD)", "1080p (Full HD)"],
            "x-enum-searchable": True,
            "ui:category": "Video Settings",
            "ui:show-if": _VEO_SHOW_IF,
        }
    )
    veo_negative_prompt: str = Field(
        default="",
        title="Negative Prompt",
        json_schema_extra={
            "ui:widget": "textarea",
            "ui:category": "Video Settings",
            "ui:help": "Content to exclude from the generated video.",
            "ui:show-if": _VEO_SHOW_IF,
        }
    )
    veo_image_url: str = Field(
        default="",
        title="Image (First Frame)",
        json_schema_extra={
            "ui:widget": "veo_image_upload",
            "ui:category": "Video Settings",
            "ui:help": "Optional image to animate as the first frame (image-to-video). JPEG, PNG, or WebP.",
            "ui:show-if": _VEO_SHOW_IF,
        }
    )
