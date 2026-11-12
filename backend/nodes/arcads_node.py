"""
Arcads AI UGC video / AI-actor ad generation automation node.

Provides workflow integration with the Arcads external REST API for operations
including:
- Products: list, create, get, update, delete
- Folders / scripts: list folders, create folder, list scripts, create script,
  get script, update script
- Generation: generate videos for a script, generate video (v2), generate image
  (v2), generate talking actor (v2), generate preset (camera movement),
  Veo 3.1 text-to-video, Omnihuman
- Assets / status: list script videos, get video, get video watch link,
  get workflow run, presigned upload URL
- Catalog: list actors, list actor situations, list situations, list voices,
  list presets

Authentication: HTTP Basic auth (Client ID + Client Secret).
  Authorization: Basic base64("<clientId>:<clientSecret>")
API Base URL: https://external-api.arcads.ai (versioned per-path: /v1 and /v2)
Documentation: https://external-api.arcads.ai/docs

The API is asynchronous and poll-based: generation endpoints return a job/asset
reference; the workflow must poll a list/get endpoint for completion and then
fetch the watch link. Arcads exposes no registerable outbound-webhook
subscription system, so the trigger operation (on_generation_completed) is
poll-based: a cron schedule wakes the node, which polls a script's generated
videos and emits only the ones that newly reached a ready/completed status,
deduping on video id via a stored cursor.
"""

import base64
import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, model_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

ARCADS_API_BASE = "https://external-api.arcads.ai"


# ============================================================================
# Credential Schema
# ============================================================================


class ArcadsApiKeyCredential(BaseModel):
    """HTTP Basic auth credential for Arcads (Client ID + Client Secret)."""

    credential_type: Literal["arcads_api_key"] = Field(
        "arcads_api_key", json_schema_extra={"ui:hidden": True}
    )
    client_id: str = Field(
        ...,
        title="Client ID",
        description="Your Arcads Client ID from Settings -> Public API -> Generate credentials",
        json_schema_extra={"ui:widget": "password"},
    )
    client_secret: str = Field(
        ...,
        title="Client Secret",
        description="Your Arcads Client Secret (shown only once at generation -- copy it immediately)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Arcads Account",
        json_schema_extra={
            "x-credential-url": "https://app.arcads.ai/settings/api",
            "x-credential-instructions": (
                "Arcads API access requires the Customized (custom/enterprise) plan. "
                "Generate credentials in the Arcads dashboard at Settings -> Public API -> "
                "Generate credentials. The Client Secret is shown only once."
            ),
        },
    )


# Arcads's own MCP server: agents get its tools through a person's Arcads sign-in.
ArcadsMcpCredential = mcp_credential("arcads", "https://mcp.arcads.ai/", app="Arcads")
ArcadsCredential = Union[ArcadsApiKeyCredential, ArcadsMcpCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class ArcadsListProductsConfig(BaseModel):
    """List products in your workspace (paginated)."""

    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "const": "list_products",
            "ui:hidden": True,
            "x-category": "Products",
            "x-is-trigger": False,
            "x-display-name": "List Products",
        },
        title="List Products",
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of products per page"
    )


class ArcadsCreateProductConfig(BaseModel):
    """Create a new product."""

    operation: Literal["create_product"] = Field(
        "create_product",
        json_schema_extra={
            "const": "create_product",
            "ui:hidden": True,
            "x-category": "Products",
            "x-is-trigger": False,
            "x-display-name": "Create Product",
        },
        title="Create Product",
    )
    name: str = Field(..., title="Name", description="Name of the product")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Description of the product",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ArcadsGetProductConfig(BaseModel):
    """Fetch a single product by ID."""

    operation: Literal["get_product"] = Field(
        "get_product",
        json_schema_extra={
            "const": "get_product",
            "ui:hidden": True,
            "x-category": "Products",
            "x-is-trigger": False,
            "x-display-name": "Get Product",
        },
        title="Get Product",
    )
    product_id: str = Field(
        ...,
        title="Product",
        description="The product to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "product_id",
                "placeholder": "Select a product...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste product ID",
            }
        },
    )


class ArcadsUpdateProductConfig(BaseModel):
    """Update an existing product."""

    operation: Literal["update_product"] = Field(
        "update_product",
        json_schema_extra={
            "const": "update_product",
            "ui:hidden": True,
            "x-category": "Products",
            "x-is-trigger": False,
            "x-display-name": "Update Product",
        },
        title="Update Product",
    )
    product_id: str = Field(
        ...,
        title="Product",
        description="The product to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "product_id",
                "placeholder": "Select a product...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste product ID",
            }
        },
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the product"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New description for the product",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ArcadsDeleteProductConfig(BaseModel):
    """Delete a product by ID."""

    operation: Literal["delete_product"] = Field(
        "delete_product",
        json_schema_extra={
            "const": "delete_product",
            "ui:hidden": True,
            "x-category": "Products",
            "x-is-trigger": False,
            "x-display-name": "Delete Product",
        },
        title="Delete Product",
    )
    product_id: str = Field(
        ...,
        title="Product",
        description="The product to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "product_id",
                "placeholder": "Select a product...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste product ID",
            }
        },
    )


class ArcadsListFoldersConfig(BaseModel):
    """List folders within a product (paginated)."""

    operation: Literal["list_folders"] = Field(
        "list_folders",
        json_schema_extra={
            "const": "list_folders",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "List Folders",
        },
        title="List Folders",
    )
    product_id: str = Field(
        ...,
        title="Product",
        description="The product whose folders to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "product_id",
                "placeholder": "Select a product...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste product ID",
            }
        },
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of folders per page"
    )


class ArcadsCreateFolderConfig(BaseModel):
    """Create a new folder within a product."""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
        },
        title="Create Folder",
    )
    product_id: str = Field(
        ...,
        title="Product",
        description="The product to create the folder in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "product_id",
                "placeholder": "Select a product...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste product ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="Name of the folder")


class ArcadsListScriptsConfig(BaseModel):
    """List scripts within a folder (paginated)."""

    operation: Literal["list_scripts"] = Field(
        "list_scripts",
        json_schema_extra={
            "const": "list_scripts",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "List Scripts",
        },
        title="List Scripts",
    )
    folder_id: str = Field(
        ..., title="Folder ID", description="The folder whose scripts to list"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of scripts per page"
    )


class ArcadsCreateProjectConfig(BaseModel):
    """Create a new project (alternative container to folders)."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "const": "create_project",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
        },
        title="Create Project",
    )
    folder_id: str = Field(..., title="Folder ID")
    name: str = Field(..., title="Name")


class ArcadsActorInput(BaseModel):
    """Actor selection shared by the documented script and generation bodies."""

    situation_id: str = Field(..., title="Situation ID", alias="situationId")
    voice_id: Optional[str] = Field(None, title="Voice ID", alias="voiceId")
    model_config = ConfigDict(populate_by_name=True)


class ArcadsCreateScriptConfig(BaseModel):
    """Create a new script within a folder or project."""

    operation: Literal["create_script"] = Field(
        "create_script",
        json_schema_extra={
            "const": "create_script",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "Create Script",
        },
        title="Create Script",
    )
    name: str = Field(..., title="Name")
    text: str = Field(
        ..., title="Script Text", json_schema_extra={"ui:widget": "textarea"}
    )
    folder_id: Optional[str] = Field(None, title="Folder ID")
    project_id: Optional[str] = Field(None, title="Project ID")
    videos: Optional[List[ArcadsActorInput]] = Field(None, title="Videos")

    @model_validator(mode="after")
    def require_container(self):
        if not self.folder_id and not self.project_id:
            raise ValueError("Provide a folder ID or project ID")
        return self


class ArcadsGetScriptConfig(BaseModel):
    """Fetch a script by ID."""

    operation: Literal["get_script"] = Field(
        "get_script",
        json_schema_extra={
            "const": "get_script",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "Get Script",
        },
        title="Get Script",
    )
    script_id: str = Field(..., title="Script ID", description="The script to fetch")


class ArcadsUpdateScriptConfig(BaseModel):
    """Update a script (text, actor/situation selection, etc.)."""

    operation: Literal["update_script"] = Field(
        "update_script",
        json_schema_extra={
            "const": "update_script",
            "ui:hidden": True,
            "x-category": "Folders & Scripts",
            "x-is-trigger": False,
            "x-display-name": "Update Script",
        },
        title="Update Script",
    )
    script_id: str = Field(..., title="Script ID")
    name: Optional[str] = Field(None, title="Name")
    text: Optional[str] = Field(
        None, title="Script Text", json_schema_extra={"ui:widget": "textarea"}
    )
    folder_id: Optional[str] = Field(None, title="Folder ID")


class ArcadsGenerateScriptVideosConfig(BaseModel):
    """Trigger AI-actor video generation for a script (async)."""

    operation: Literal["generate_script_videos"] = Field(
        "generate_script_videos",
        json_schema_extra={
            "const": "generate_script_videos",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Videos for Script",
        },
        title="Generate Videos for Script",
    )
    script_id: str = Field(
        ..., title="Script ID", description="The script to generate videos for"
    )


class ArcadsGenerateVideoConfig(BaseModel):
    """Generic video generation entry point (v2, supports model selection)."""

    operation: Literal["generate_video"] = Field(
        "generate_video",
        json_schema_extra={
            "const": "generate_video",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Video (v2)",
        },
        title="Generate Video (v2)",
    )
    product_id: str = Field(..., title="Product ID")
    prompt: str = Field(
        ..., title="Prompt", json_schema_extra={"ui:widget": "textarea"}
    )
    model: Literal[
        "veo31",
        "kling-2.6",
        "kling-3.0",
        "kling-4.0",
        "grok-video",
        "seedance",
        "seedance-2.0",
        "seedance-2.0-mini",
        "seedance-2.5",
        "happy-horse",
        "minimax-h3",
        "minimax-h3-max",
    ] = Field(..., title="Model")
    project_id: Optional[str] = Field(None, title="Project ID")
    aspect_ratio: Optional[str] = Field(None, title="Aspect Ratio")
    resolution: Optional[str] = Field(None, title="Resolution")
    duration: Optional[float] = Field(None, title="Duration (seconds)")
    reference_images: Optional[List[str]] = Field(None, title="Reference Image Paths")


class ArcadsGenerateImageConfig(BaseModel):
    """Trigger image generation (v2)."""

    operation: Literal["generate_image"] = Field(
        "generate_image",
        json_schema_extra={
            "const": "generate_image",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Image (v2)",
        },
        title="Generate Image (v2)",
    )
    product_id: str = Field(..., title="Product ID")
    prompt: str = Field(
        ..., title="Prompt", json_schema_extra={"ui:widget": "textarea"}
    )
    model: Literal[
        "gpt-image",
        "gpt-image-2",
        "gpt-image-2-5-flare",
        "gpt-image-2-5-sunburst",
        "gpt-image-2-6-flare",
        "gpt-image-2-6-sunburst",
        "nano-banana",
        "nano-banana-2",
        "nano-banana-2-1",
        "soul",
        "grok_image",
        "seedream",
        "seedream_5_lite",
        "seedream_5_pro",
    ] = Field(..., title="Model")
    aspect_ratio: Literal[
        "21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "2:3", "3:2", "4:5", "1:2", "2:1"
    ] = Field(..., title="Aspect Ratio")
    project_id: Optional[str] = Field(None, title="Project ID")
    reference_images: Optional[List[str]] = Field(None, title="Reference Image Paths")


class ArcadsGenerateTalkingActorConfig(BaseModel):
    """Generate a talking-actor (lip-synced) video (v2)."""

    operation: Literal["generate_talking_actor"] = Field(
        "generate_talking_actor",
        json_schema_extra={
            "const": "generate_talking_actor",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Talking Actor (v2)",
        },
        title="Generate Talking Actor (v2)",
    )
    product_id: str = Field(..., title="Product ID")
    text: str = Field(..., title="Script", json_schema_extra={"ui:widget": "textarea"})
    model: Literal["arcads_1.0", "audio_driven", "omnihuman"] = Field(
        ..., title="Model"
    )
    actors: List[ArcadsActorInput] = Field(..., title="Actors", min_length=1)
    project_id: Optional[str] = Field(None, title="Project ID")


class ArcadsGeneratePresetConfig(BaseModel):
    """Trigger a camera-movement preset generation."""

    operation: Literal["generate_preset"] = Field(
        "generate_preset",
        json_schema_extra={
            "const": "generate_preset",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Preset (Camera Movement)",
        },
        title="Generate Preset (Camera Movement)",
    )
    product_id: str = Field(..., title="Product ID")
    situation_id: str = Field(..., title="Situation ID")
    reference_images: List[str] = Field(
        ..., title="Reference Image Paths", min_length=1
    )
    project_id: Optional[str] = Field(None, title="Project ID")
    aspect_ratio: Optional[
        Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
    ] = Field(None, title="Aspect Ratio")
    strength: Optional[float] = Field(None, title="Camera Movement Strength")


class ArcadsGenerateVeo31Config(BaseModel):
    """Trigger Veo 3.1 text-to-video generation."""

    operation: Literal["generate_veo31"] = Field(
        "generate_veo31",
        json_schema_extra={
            "const": "generate_veo31",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Veo 3.1 Text-to-Video",
        },
        title="Veo 3.1 Text-to-Video",
    )
    product_id: str = Field(..., title="Product ID")
    prompt: str = Field(
        ..., title="Prompt", json_schema_extra={"ui:widget": "textarea"}
    )
    resolution: Literal["360p", "480p", "720p", "1080p", "4K"] = Field(
        ..., title="Resolution"
    )
    aspect_ratio: Literal["16:9", "9:16"] = Field(..., title="Aspect Ratio")
    project_id: Optional[str] = Field(None, title="Project ID")
    reference_images: Optional[List[str]] = Field(None, title="Reference Image Paths")


class ArcadsGenerateOmnihumanConfig(BaseModel):
    """Trigger Omnihuman avatar / talking-head generation."""

    operation: Literal["generate_omnihuman"] = Field(
        "generate_omnihuman",
        json_schema_extra={
            "const": "generate_omnihuman",
            "ui:hidden": True,
            "x-category": "Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Omnihuman",
        },
        title="Generate Omnihuman",
    )
    product_id: str = Field(..., title="Product ID")
    text: str = Field(
        ..., title="Script Text", json_schema_extra={"ui:widget": "textarea"}
    )
    videos: List[ArcadsActorInput] = Field(..., title="Videos", min_length=1)


class ArcadsListScriptVideosConfig(BaseModel):
    """Get generated videos for a script -- poll this for status + download link."""

    operation: Literal["list_script_videos"] = Field(
        "list_script_videos",
        json_schema_extra={
            "const": "list_script_videos",
            "ui:hidden": True,
            "x-category": "Assets & Status",
            "x-is-trigger": False,
            "x-display-name": "List Script Videos",
        },
        title="List Script Videos",
    )
    script_id: str = Field(
        ..., title="Script ID", description="The script whose videos to list"
    )


class ArcadsGetVideoConfig(BaseModel):
    """Fetch a single video by ID (status)."""

    operation: Literal["get_video"] = Field(
        "get_video",
        json_schema_extra={
            "const": "get_video",
            "ui:hidden": True,
            "x-category": "Assets & Status",
            "x-is-trigger": False,
            "x-display-name": "Get Video",
        },
        title="Get Video",
    )
    video_id: str = Field(..., title="Video ID", description="The video to fetch")


class ArcadsGetVideoWatchConfig(BaseModel):
    """Get a playable/downloadable watch URL for a video."""

    operation: Literal["get_video_watch"] = Field(
        "get_video_watch",
        json_schema_extra={
            "const": "get_video_watch",
            "ui:hidden": True,
            "x-category": "Assets & Status",
            "x-is-trigger": False,
            "x-display-name": "Get Video Watch Link",
        },
        title="Get Video Watch Link",
    )
    video_id: str = Field(
        ..., title="Video ID", description="The video to get a watch link for"
    )


class ArcadsGetWorkflowRunConfig(BaseModel):
    """Check the status of a workflow run."""

    operation: Literal["get_workflow_run"] = Field(
        "get_workflow_run",
        json_schema_extra={
            "const": "get_workflow_run",
            "ui:hidden": True,
            "x-category": "Assets & Status",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Run",
        },
        title="Get Workflow Run",
    )
    run_id: str = Field(..., title="Run ID", description="The workflow run to check")


class ArcadsGetPresignedUrlConfig(BaseModel):
    """Get a presigned URL to upload a source file."""

    operation: Literal["get_presigned_url"] = Field(
        "get_presigned_url",
        json_schema_extra={
            "const": "get_presigned_url",
            "ui:hidden": True,
            "x-category": "Assets & Status",
            "x-is-trigger": False,
            "x-display-name": "Get Presigned Upload URL",
        },
        title="Get Presigned Upload URL",
    )
    file_type: Literal[
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/heic",
        "image/heif",
        "video/mp4",
        "video/quicktime",
        "video/avi",
        "video/mov",
        "video/wmv",
        "video/webm",
        "audio/mp3",
        "audio/mp4",
        "audio/wav",
        "audio/m4a",
        "audio/x-m4a",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
        "audio/webm",
        "audio/mpeg",
        "audio/opus",
        "application/pdf",
        "text/plain",
        "text/html",
        "text/markdown",
        "text/x-markdown",
        "text/md",
        "text/csv",
        "text/x-csv",
        "application/csv",
        "application/x-csv",
        "text/comma-separated-values",
        "text/x-comma-separated-values",
        "application/json",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.apple.pages",
        "application/vnd.apple.numbers",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.drawing",
        "application/x-iwork-pages-sffpages",
        "application/x-iwork-numbers-sffnumbers",
    ] = Field(..., title="File MIME Type")


class ArcadsListActorsConfig(BaseModel):
    """List AI actors with optional filters (paginated)."""

    operation: Literal["list_actors"] = Field(
        "list_actors",
        json_schema_extra={
            "const": "list_actors",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Actors",
        },
        title="List Actors",
    )
    age: Optional[str] = Field(None, title="Age", description="Filter by age group")
    gender: Optional[str] = Field(
        None,
        title="Gender",
        description="Filter by gender",
        json_schema_extra={
            "enum": ["", "male", "female"],
            "enumNames": ["Any", "Male", "Female"],
            "x-enum-searchable": True,
        },
    )
    skin_tone: Optional[str] = Field(
        None, title="Skin Tone", description="Filter by skin tone"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of actors per page"
    )


class ArcadsListActorSituationsConfig(BaseModel):
    """List situations (scene contexts) available for a given actor."""

    operation: Literal["list_actor_situations"] = Field(
        "list_actor_situations",
        json_schema_extra={
            "const": "list_actor_situations",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Actor Situations",
        },
        title="List Actor Situations",
    )
    actor_id: str = Field(
        ...,
        title="Actor",
        description="The actor whose situations to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "actor_id",
                "placeholder": "Select an actor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste actor ID",
            }
        },
    )


class ArcadsListSituationsConfig(BaseModel):
    """List situations with optional filters (paginated)."""

    operation: Literal["list_situations"] = Field(
        "list_situations",
        json_schema_extra={
            "const": "list_situations",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Situations",
        },
        title="List Situations",
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of situations per page"
    )


class ArcadsListVoicesConfig(BaseModel):
    """List AI voices with optional filters (paginated)."""

    operation: Literal["list_voices"] = Field(
        "list_voices",
        json_schema_extra={
            "const": "list_voices",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Voices",
        },
        title="List Voices",
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Number of voices per page"
    )


class ArcadsListPresetsConfig(BaseModel):
    """List available preset types."""

    operation: Literal["list_presets"] = Field(
        "list_presets",
        json_schema_extra={
            "const": "list_presets",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Presets",
        },
        title="List Presets",
    )


# ============================================================================
# Trigger (poll-based)
# ============================================================================


class ArcadsOnGenerationCompletedConfig(BaseModel):
    """Poll a script's generated videos and trigger when one newly completes.

    Arcads has no outbound webhooks, so this is poll-based: a cron schedule wakes
    the node, which lists the script's videos and emits only those that reached a
    ready/completed status and were not seen on a previous poll (dedup on video
    id via the hidden last_seen_ids cursor)."""

    operation: Literal["on_generation_completed"] = Field(
        "on_generation_completed",
        title="On Generation Completed",
        description="Trigger when a script's generated videos newly complete",
        json_schema_extra={
            "ui:hidden": True,
            "const": "on_generation_completed",
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Generation Completed",
        },
    )
    script_id: str = Field(
        ...,
        title="Script",
        description="The script whose generated videos to watch for completion",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "script_id",
                "placeholder": "Select a script...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste script ID",
            }
        },
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll the script for newly completed videos",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Hidden internal fields for webhook/schedule management
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "ui:hidden": True,
            "ui:loadValue": True,
            "ui:copyable": True,
        },
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Cursor: ids of videos already emitted, so we never re-emit a completed video
    last_seen_ids: Optional[List[str]] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


ArcadsConfig = Annotated[
    Union[
        ArcadsListProductsConfig,
        ArcadsCreateProductConfig,
        ArcadsGetProductConfig,
        ArcadsUpdateProductConfig,
        ArcadsDeleteProductConfig,
        ArcadsListFoldersConfig,
        ArcadsCreateFolderConfig,
        ArcadsListScriptsConfig,
        ArcadsCreateProjectConfig,
        ArcadsCreateScriptConfig,
        ArcadsGetScriptConfig,
        ArcadsUpdateScriptConfig,
        ArcadsGenerateScriptVideosConfig,
        ArcadsGenerateVideoConfig,
        ArcadsGenerateImageConfig,
        ArcadsGenerateTalkingActorConfig,
        ArcadsGeneratePresetConfig,
        ArcadsGenerateVeo31Config,
        ArcadsGenerateOmnihumanConfig,
        ArcadsListScriptVideosConfig,
        ArcadsGetVideoConfig,
        ArcadsGetVideoWatchConfig,
        ArcadsGetWorkflowRunConfig,
        ArcadsGetPresignedUrlConfig,
        ArcadsListActorsConfig,
        ArcadsListActorSituationsConfig,
        ArcadsListSituationsConfig,
        ArcadsListVoicesConfig,
        ArcadsListPresetsConfig,
        # Trigger
        ArcadsOnGenerationCompletedConfig,
    ],
    Discriminator("operation"),
]


class ArcadsNodeConfig(NodeConfig[ArcadsConfig, ArcadsCredential]):
    """Full configuration for the Arcads node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {token}"


async def _arcads_request(
    client_id: str,
    client_secret: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Arcads request and return a structured result."""
    url = f"{ARCADS_API_BASE}{endpoint}"
    headers = {
        "Authorization": _basic_auth_header(client_id, client_secret),
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("message") or err.get("error") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ArcadsNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ArcadsNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class ArcadsNode(WorkflowNode):
    """Arcads AI UGC video / AI-actor ad generation automation node."""

    integration_type = "automation-arcads"

    credential_provider_labels = {"arcads": "Arcads Account"}
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products")

    edit_examples = [
        "Create a product and generate AI-actor videos for a script",
        "Generate a Veo 3.1 video from a prompt",
        "List available AI actors filtered by gender",
        "Poll a script for its generated videos and fetch the watch link",
        "Generate a talking-actor lip-synced video",
    ]

    @classmethod
    def get_config_model(cls):
        return ArcadsNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Arcads trigger is poll-based: the webhook is a wake-up signal, not data.
        Return None so execute() runs and actually polls the Arcads API."""
        if config.get("operation") == "on_generation_completed":
            return None
        return payload

    # ------------------------------------------------------------------
    # Trigger: webhook + cron schedule provisioning
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the webhook + polling schedule for the trigger operation
        (same pattern as Gmail/Cron trigger nodes)."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name == "webhook_url":
            webhook_data = await WebhookManager.get_or_create_webhook(
                pool=pool,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
            )

            webhook_id = webhook_data.get("webhook_id")
            webhook_url = webhook_data.get("webhook_url")

            schedule = {"frequency": "minutes", "interval": 5}
            if context and "schedule" in context and context["schedule"]:
                schedule = context["schedule"]
            cron_expression = schedule_to_cron(schedule)
            logger.info(
                f"[ArcadsNode] Trigger schedule {schedule} -> cron: {cron_expression}"
            )

            existing_schedule_id = context.get("schedule_id") if context else None
            schedule_id = existing_schedule_id
            next_run = None

            if is_cron_scheduler_enabled() and webhook_url:
                if existing_schedule_id:
                    result = await update_schedule(
                        schedule_id=existing_schedule_id,
                        cron_expression=cron_expression,
                    )
                    if result.get("success"):
                        next_run = result.get("next_run")
                    elif "error" in result:
                        logger.warning(
                            f"[ArcadsNode] Failed to update schedule: {result['error']}"
                        )
                        existing_schedule_id = None

                if not existing_schedule_id:
                    result = await create_schedule(
                        user_id=user_id,
                        workflow_id=str(workflow_id),
                        node_id=node_id,
                        cron_expression=cron_expression,
                        webhook_url=webhook_url,
                        payload={"source": "arcads_trigger", "node_id": node_id},
                    )
                    if "id" in result:
                        schedule_id = result["id"]
                        next_run = result.get("next_run")
                    elif "error" in result:
                        logger.warning(
                            f"[ArcadsNode] Failed to create schedule: {result['error']}"
                        )

            interval_ms = schedule_to_interval_ms(schedule)

            return {
                "values": {
                    "webhook_id": webhook_id,
                    "webhook_url": webhook_url,
                    "schedule_id": schedule_id,
                    "next_run": next_run,
                    "interval_ms": interval_ms,
                }
            }

        return {"value": None}

    # ------------------------------------------------------------------
    # Dynamic options (products, actors, voices)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        endpoint_map = {
            "product_id": ("/v1/products", "products"),
            "actor_id": ("/v1/actors", "actors"),
            "voice_id": ("/v1/voices", "voices"),
        }
        if field_name not in endpoint_map:
            return {"options": []}
        # Staging resolves and admits the saved credential before this hook.
        # Arcads uses static Basic-auth credentials, so no refresh is needed.
        if not credential_data:
            return {"options": []}
        credential = ArcadsApiKeyCredential.model_validate(credential_data)
        client_id = credential.client_id
        client_secret = credential.client_secret
        endpoint, _label = endpoint_map[field_name]
        result = await _arcads_request(
            client_id,
            client_secret,
            "GET",
            endpoint,
            params={"pageSize": "100"},
            action_name=f"load_{field_name}",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data")
        items = cls._extract_list(data)
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            name = (
                item.get("name")
                or item.get("title")
                or item.get("displayName")
                or f"{item_id}"
            )
            if item_id is not None:
                options.append({"label": str(name), "value": str(item_id)})
        return {"options": options}

    @staticmethod
    def _extract_list(data: Any) -> list:
        """Pull a list of items out of a paginated/wrapped Arcads payload."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "results", "products", "actors", "voices"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ArcadsNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Arcads Client ID and Client Secret."
            )
        client_id = credentials.client_id
        client_secret = credentials.client_secret

        handlers = {
            "list_products": self._list_products,
            "create_product": self._create_product,
            "get_product": self._get_product,
            "update_product": self._update_product,
            "delete_product": self._delete_product,
            "list_folders": self._list_folders,
            "create_folder": self._create_folder,
            "list_scripts": self._list_scripts,
            "create_project": self._create_project,
            "create_script": self._create_script,
            "get_script": self._get_script,
            "update_script": self._update_script,
            "generate_script_videos": self._generate_script_videos,
            "generate_video": self._generate_video,
            "generate_image": self._generate_image,
            "generate_talking_actor": self._generate_talking_actor,
            "generate_preset": self._generate_preset,
            "generate_veo31": self._generate_veo31,
            "generate_omnihuman": self._generate_omnihuman,
            "list_script_videos": self._list_script_videos,
            "get_video": self._get_video,
            "get_video_watch": self._get_video_watch,
            "get_workflow_run": self._get_workflow_run,
            "get_presigned_url": self._get_presigned_url,
            "list_actors": self._list_actors,
            "list_actor_situations": self._list_actor_situations,
            "list_situations": self._list_situations,
            "list_voices": self._list_voices,
            "list_presets": self._list_presets,
            "on_generation_completed": self._on_generation_completed,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, client_id, client_secret)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Products
    # ------------------------------------------------------------------
    async def _list_products(
        self, c: ArcadsListProductsConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            "/v1/products",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="list_products",
        )

    async def _create_product(
        self, c: ArcadsCreateProductConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/products",
            json_body={"name": c.name, "description": c.description},
            action_name="create_product",
        )

    async def _get_product(self, c: ArcadsGetProductConfig, cid, sec) -> Dict[str, Any]:
        return await _arcads_request(
            cid, sec, "GET", f"/v1/products/{c.product_id}", action_name="get_product"
        )

    async def _update_product(
        self, c: ArcadsUpdateProductConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "PUT",
            f"/v1/products/{c.product_id}",
            json_body={"name": c.name, "description": c.description},
            action_name="update_product",
        )

    async def _delete_product(
        self, c: ArcadsDeleteProductConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "DELETE",
            f"/v1/products/{c.product_id}",
            action_name="delete_product",
        )

    # ------------------------------------------------------------------
    # Handlers — Folders & Scripts
    # ------------------------------------------------------------------
    async def _list_folders(
        self, c: ArcadsListFoldersConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/products/{c.product_id}/folders",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="list_folders",
        )

    async def _create_folder(
        self, c: ArcadsCreateFolderConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/folders",
            json_body={"name": c.name, "productId": c.product_id},
            action_name="create_folder",
        )

    async def _list_scripts(
        self, c: ArcadsListScriptsConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/folders/{c.folder_id}/scripts",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="list_scripts",
        )

    async def _create_project(
        self, c: ArcadsCreateProjectConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/projects",
            json_body={"name": c.name, "folderId": c.folder_id},
            action_name="create_project",
        )

    async def _create_script(
        self, c: ArcadsCreateScriptConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/scripts",
            json_body={
                "text": c.text,
                "folderId": c.folder_id,
                "projectId": c.project_id,
                "name": c.name,
                "videos": [
                    v.model_dump(by_alias=True, exclude_none=True) for v in c.videos
                ]
                if c.videos is not None
                else None,
            },
            action_name="create_script",
        )

    async def _get_script(self, c: ArcadsGetScriptConfig, cid, sec) -> Dict[str, Any]:
        return await _arcads_request(
            cid, sec, "GET", f"/v1/scripts/{c.script_id}", action_name="get_script"
        )

    async def _update_script(
        self, c: ArcadsUpdateScriptConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "PUT",
            f"/v1/scripts/{c.script_id}",
            json_body={
                "text": c.text,
                "name": c.name,
                "folderId": c.folder_id,
            },
            action_name="update_script",
        )

    # ------------------------------------------------------------------
    # Handlers — Generation
    # ------------------------------------------------------------------
    async def _generate_script_videos(
        self, c: ArcadsGenerateScriptVideosConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            f"/v1/scripts/{c.script_id}/generate",
            json_body={},
            action_name="generate_script_videos",
        )

    async def _generate_video(
        self, c: ArcadsGenerateVideoConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v2/videos/generate",
            json_body={
                "prompt": c.prompt,
                "productId": c.product_id,
                "projectId": c.project_id,
                "model": c.model,
                "aspectRatio": c.aspect_ratio,
                "resolution": c.resolution,
                "duration": c.duration,
                "referenceImages": c.reference_images,
            },
            action_name="generate_video",
        )

    async def _generate_image(
        self, c: ArcadsGenerateImageConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v2/images/generate",
            json_body={
                "prompt": c.prompt,
                "model": c.model,
                "productId": c.product_id,
                "projectId": c.project_id,
                "aspectRatio": c.aspect_ratio,
                "referenceImages": c.reference_images,
            },
            action_name="generate_image",
        )

    async def _generate_talking_actor(
        self, c: ArcadsGenerateTalkingActorConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v2/talking-actors/generate",
            json_body={
                "script": c.text,
                "productId": c.product_id,
                "projectId": c.project_id,
                "model": c.model,
                "actors": [
                    a.model_dump(by_alias=True, exclude_none=True) for a in c.actors
                ],
            },
            action_name="generate_talking_actor",
        )

    async def _generate_preset(
        self, c: ArcadsGeneratePresetConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/presets/camera-movement/generate",
            json_body={
                "productId": c.product_id,
                "projectId": c.project_id,
                "situationId": c.situation_id,
                "referenceImages": c.reference_images,
                "aspectRatio": c.aspect_ratio,
                "strength": c.strength,
            },
            action_name="generate_preset",
        )

    async def _generate_veo31(
        self, c: ArcadsGenerateVeo31Config, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/veo31/generate/video",
            json_body={
                "prompt": c.prompt,
                "productId": c.product_id,
                "projectId": c.project_id,
                "resolution": c.resolution,
                "aspectRatio": c.aspect_ratio,
                "referenceImages": c.reference_images,
            },
            action_name="generate_veo31",
        )

    async def _generate_omnihuman(
        self, c: ArcadsGenerateOmnihumanConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/omnihuman",
            json_body={
                "text": c.text,
                "productId": c.product_id,
                "videos": [
                    v.model_dump(by_alias=True, exclude_none=True) for v in c.videos
                ],
            },
            action_name="generate_omnihuman",
        )

    # ------------------------------------------------------------------
    # Handlers — Assets & Status
    # ------------------------------------------------------------------
    async def _list_script_videos(
        self, c: ArcadsListScriptVideosConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/scripts/{c.script_id}/videos",
            action_name="list_script_videos",
        )

    async def _get_video(self, c: ArcadsGetVideoConfig, cid, sec) -> Dict[str, Any]:
        return await _arcads_request(
            cid, sec, "GET", f"/v1/videos/{c.video_id}", action_name="get_video"
        )

    async def _get_video_watch(
        self, c: ArcadsGetVideoWatchConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/videos/{c.video_id}/watch",
            action_name="get_video_watch",
        )

    async def _get_workflow_run(
        self, c: ArcadsGetWorkflowRunConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/workflows/runs/{c.run_id}",
            action_name="get_workflow_run",
        )

    async def _get_presigned_url(
        self, c: ArcadsGetPresignedUrlConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "POST",
            "/v1/file-upload/get-presigned-url",
            json_body={"fileType": c.file_type},
            action_name="get_presigned_url",
        )

    # ------------------------------------------------------------------
    # Handlers — Catalog
    # ------------------------------------------------------------------
    async def _list_actors(self, c: ArcadsListActorsConfig, cid, sec) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            "/v1/actors",
            params={
                "age": c.age,
                "gender": c.gender or None,
                "skinTone": c.skin_tone,
                "page": c.page,
                "pageSize": c.page_size,
            },
            action_name="list_actors",
        )

    async def _list_actor_situations(
        self, c: ArcadsListActorSituationsConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/actors/{c.actor_id}/situations",
            action_name="list_actor_situations",
        )

    async def _list_situations(
        self, c: ArcadsListSituationsConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            "/v1/situations",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="list_situations",
        )

    async def _list_voices(self, c: ArcadsListVoicesConfig, cid, sec) -> Dict[str, Any]:
        return await _arcads_request(
            cid,
            sec,
            "GET",
            "/v1/voices",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="list_voices",
        )

    async def _list_presets(
        self, c: ArcadsListPresetsConfig, cid, sec
    ) -> Dict[str, Any]:
        return await _arcads_request(
            cid, sec, "GET", "/v1/presets", action_name="list_presets"
        )

    # ------------------------------------------------------------------
    # Handlers — Trigger (poll-based)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_video_completed(video: Dict[str, Any]) -> bool:
        """A video counts as completed once it carries a terminal/ready status."""
        status = str(video.get("status", "")).lower()
        return status in ("ready", "completed", "done", "success", "finished")

    async def _on_generation_completed(
        self, c: ArcadsOnGenerationCompletedConfig, cid, sec
    ) -> Dict[str, Any]:
        """Poll the script's generated videos and emit only those that newly
        reached a completed status (dedup on video id via a persisted cursor)."""
        result = await _arcads_request(
            cid,
            sec,
            "GET",
            f"/v1/scripts/{c.script_id}/videos",
            action_name="on_generation_completed",
        )
        if result.get("status") != "success":
            # Surface the upstream error unchanged so the run reflects the failure.
            return result

        videos = self._extract_list(result.get("data"))

        # Cursor = ids already emitted. Config supplies an initial seed; persisted
        # node state carries it forward across webhook-driven poll executions.
        stored_state = await self._load_node_state()
        seen_ids = set(stored_state.get("last_seen_ids") or [])
        if c.last_seen_ids:
            seen_ids.update(c.last_seen_ids)

        new_items = []
        completed_ids = set()
        for video in videos:
            if not isinstance(video, dict):
                continue
            vid = video.get("id")
            if vid is None or not self._is_video_completed(video):
                continue
            vid = str(vid)
            completed_ids.add(vid)
            if vid not in seen_ids:
                new_items.append(video)

        updated_seen = sorted(seen_ids | completed_ids)
        await self._save_node_state({"last_seen_ids": updated_seen})

        return {
            "status": "success",
            "operation": "on_generation_completed",
            "action": "on_generation_completed",
            "script_id": c.script_id,
            "items": new_items,
            "new_count": len(new_items),
            "last_seen_ids": updated_seen,
            "timestamp": time.time(),
        }
