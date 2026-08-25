"""Kling video/image generation config — all 18 Kling-specific fields scoped here."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields


class KlingConfig(BaseAgentFields):
    """Configuration for ByteDance Kling video/image generation."""
    model_type: Literal["kling"] = Field(
        default="kling",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default="kling/kling-v2-master",
        title="Model",
        description="Kling model variant",
        json_schema_extra={
            "x-queryable-enum": "models",
            "x-enum-hint": (
                "Kling model identifier (kling/...). Fuzzy input is auto-resolved "
                "to the closest registered id."
            ),
        },
    )
    kling_mode: str = Field(
        default="std",
        title="Quality Mode",
        json_schema_extra={
            "enum": ["std", "pro"],
            "enumNames": ["Standard (~30s generation)", "Professional (~60s, higher quality)"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:show-if": {"field": "model", "contains": "kling", "notContains": "image"},
        }
    )
    kling_duration: str = Field(
        default="5",
        title="Duration (seconds)",
        json_schema_extra={
            "enum": ["5", "10"],
            "enumNames": ["5 seconds", "10 seconds"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:show-if": {"field": "model", "contains": "kling", "notContains": "image"},
        }
    )
    kling_aspect_ratio: str = Field(
        default="16:9",
        title="Aspect Ratio",
        json_schema_extra={
            "enum": ["16:9", "9:16", "1:1"],
            "enumNames": ["16:9 (Landscape)", "9:16 (Portrait)", "1:1 (Square)"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:show-if": {"field": "model", "contains": "kling"},
        }
    )
    kling_negative_prompt: str = Field(
        default="",
        title="Negative Prompt",
        json_schema_extra={
            "ui:widget": "textarea",
            "ui:category": "Kling Settings",
            "ui:help": "Content to exclude from the generated video/image (max 2500 chars).",
            "ui:show-if": {"field": "model", "containsAny": [
                "kling-v1-6", "kling-v1-5", "kling/kling-v1",
                "kling-v2-5-turbo", "kling-v2-6",
                "kling-v3", "kling-v3-omni",
                "kling-image",
            ]},
        }
    )
    kling_image_url: str = Field(
        default="",
        title="Image (First Frame)",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Optional image to animate as the first frame (image-to-video). JPEG, PNG, or WebP.",
            "ui:widget": "veo_image_upload",
            "ui:show-if": {"field": "model", "contains": "kling"},
        }
    )
    kling_image_tail_url: str = Field(
        default="",
        title="Image (Last Frame)",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "End-frame image for image-to-video (pro mode). Controls where the video ends.",
            "ui:widget": "veo_image_upload",
            "ui:show-if": {"field": "model", "containsAny": [
                "kling-v1-6", "kling-v2-1", "kling-v2-6",
                "kling-v3", "kling-v3-omni", "kling-video-o1",
            ]},
        }
    )
    kling_cfg_scale: str = Field(
        default="0.5",
        title="Creativity (cfg_scale)",
        json_schema_extra={
            "enum": ["0", "0.25", "0.5", "0.75", "1"],
            "enumNames": ["0 (Max creativity)", "0.25", "0.5 (Balanced)", "0.75", "1 (Strict prompt)"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:help": "Controls how closely the output follows the prompt. Lower = more creative.",
            "ui:show-if": {"field": "model", "containsAny": [
                "kling/kling-v1", "kling-v1-5", "kling-v1-6",
                "kling-v3", "kling-video-o1",
            ]},
        }
    )
    kling_seed: str = Field(
        default="",
        title="Seed",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Optional seed for reproducible results. Leave empty for random.",
            "ui:show-if": {"field": "model", "contains": "kling"},
        }
    )
    kling_sound: str = Field(
        default="off",
        title="Sound Generation",
        json_schema_extra={
            "enum": ["off", "on"],
            "enumNames": ["Off", "On"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:help": "Generate synchronized audio.",
            "ui:show-if": {"field": "model", "containsAny": [
                "kling-v2-5-turbo", "kling-v2-6",
                "kling-v3", "kling-v3-omni", "kling-video-o1",
            ]},
        }
    )
    kling_camera_type: str = Field(
        default="",
        title="Camera Movement",
        json_schema_extra={
            "enum": ["", "simple", "down_back", "forward_up", "right_turn_forward", "left_turn_forward"],
            "enumNames": ["None", "Simple (manual control)", "Down & Back", "Forward & Up", "Right Turn Forward", "Left Turn Forward"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:help": "Camera movement preset. 'Simple' allows manual horizontal/vertical/zoom/pan/tilt/roll.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_horizontal: str = Field(
        default="0",
        title="Camera Horizontal",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Horizontal camera movement (-10 to 10). Only used when camera is 'Simple'.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_vertical: str = Field(
        default="0",
        title="Camera Vertical",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Vertical camera movement (-10 to 10). Only used when camera is 'Simple'.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_zoom: str = Field(
        default="0",
        title="Camera Zoom",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Zoom level (-10 to 10). Positive = zoom in, negative = zoom out.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_pan: str = Field(
        default="0",
        title="Camera Pan",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Pan rotation (-10 to 10). Only used when camera is 'Simple'.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_tilt: str = Field(
        default="0",
        title="Camera Tilt",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Tilt rotation (-10 to 10). Only used when camera is 'Simple'.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_camera_roll: str = Field(
        default="0",
        title="Camera Roll",
        json_schema_extra={
            "ui:category": "Kling Settings",
            "ui:help": "Roll rotation (-10 to 10). Only used when camera is 'Simple'.",
            "ui:show-if": {"field": "model", "contains": "kling-v1-6"},
        }
    )
    kling_image_count: str = Field(
        default="1",
        title="Number of Images",
        json_schema_extra={
            "enum": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
            "enumNames": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
            "x-enum-searchable": True,
            "ui:category": "Kling Settings",
            "ui:help": "Number of images to generate (1-9). Only applies to image generation models.",
            "ui:show-if": {"field": "model", "contains": "kling-image"},
        }
    )
