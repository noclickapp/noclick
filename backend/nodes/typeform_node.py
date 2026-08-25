"""
Typeform REST API automation node.

Provides workflow integration with Typeform for operations including:
- Form Operations: list, get, create, update, delete forms and custom messages
- Theme Operations: list, get, create, update, delete themes
- Image Operations: list, get, create, delete images (various sizes)
- Video Operations: upload videos
- Workspace Operations: list, get, create, update, delete workspaces
- Response Operations: retrieve, delete responses, download files, get insights
- Webhook Operations: create, update, delete webhooks
- Translation Operations: get, create, update, delete, auto-translate forms

Authentication: Personal Access Token (PAT) or OAuth 2.0
API Base URL: https://api.typeform.com
Documentation: https://www.typeform.com/developers/
Rate Limit: 2 requests per second per account
"""

import logging
import secrets
import time
from typing import Dict, Any, Optional, List, Literal, Tuple, Union, Annotated
from pydantic import BaseModel, ConfigDict, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import (
    load_paginated_options,
    require_credential_token,
)
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.oauth.typeform_oauth import is_token_expired, refresh_access_token
from utils.webhook_signatures import verify_hmac_sha256_base64
from nodes.scopes.content_storage import TYPEFORM_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TYPEFORM_API_BASE = "https://api.typeform.com"


# ============================================================================
# Webhook trigger helpers
# ============================================================================


def _typeform_webhook_tag(node_id: str) -> str:
    """Deterministic Typeform webhook tag for a workflow node.

    Typeform webhooks are keyed by ``(form_id, tag)`` and ``PUT`` is idempotent
    on the tag, so deriving the tag from the node id makes registration and
    cleanup repeatable without storing an external id.
    """
    return f"noclick-{node_id}"


def _typeform_token_from_credential(credential: Dict[str, Any]) -> Optional[str]:
    """Extract a usable bearer token from a decrypted Typeform credential
    (Personal Access Token or OAuth)."""
    return (credential or {}).get("personal_access_token") or (
        credential or {}
    ).get("access_token")


async def register_typeform_webhook(
    token: str, form_id: str, tag: str, webhook_url: str, secret: str
) -> Dict[str, Any]:
    """Create or update a Typeform webhook for a form (PUT is idempotent)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            f"{TYPEFORM_API_BASE}/forms/{form_id}/webhooks/{tag}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "url": webhook_url,
                "enabled": True,
                "secret": secret,
                "verify_ssl": True,
            },
        )
        response.raise_for_status()
        return response.json() if response.content else {}


async def unregister_typeform_webhook(token: str, form_id: str, tag: str) -> None:
    """Delete a Typeform webhook. A missing webhook (404) is treated as done."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{TYPEFORM_API_BASE}/forms/{form_id}/webhooks/{tag}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

# ============================================================================
# Credential Schema
# ============================================================================


class TypeformPATCredential(BaseModel):
    """
    Personal Access Token credential for Typeform.

    Get your PAT at: https://admin.typeform.com/account#/section/tokens
    """

    credential_type: Literal["typeform_pat"] = Field(
        "typeform_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="Your Typeform Personal Access Token (PAT)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://admin.typeform.com/account#/section/tokens"
    })


class TypeformOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Typeform.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://admin.typeform.com/account#/section/tokens

    Note: Refresh tokens are only available for standard OAuth apps.
    Personal Access Token apps don't support refresh tokens.
    """

    credential_type: Literal["typeform_oauth"] = Field(
        "typeform_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Typeform"
    )
    refresh_token: Optional[str] = Field(
        None,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal (only for standard OAuth apps)",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected Typeform account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "typeform",
        "x-oauth-scopes": [
            # Note: 'offline' scope excluded - only works with standard OAuth apps.
            # NoClick's registered Typeform app rejects token exchange with
            # "this kind of access tokens cannot have refresh tokens" if 'offline'
            # is requested. Do not re-add it (regression 2026-08-04).
            "accounts:read",
            "forms:read",
            "forms:write",
            "images:read",
            "images:write",
            "themes:read",
            "themes:write",
            "responses:read",
            "responses:write",
            "webhooks:read",
            "webhooks:write",
            "workspaces:read",
            "workspaces:write",
        ],
    })


# Union type for credentials - supports both PAT and OAuth
TypeformCredential = Union[TypeformOAuthCredential, TypeformPATCredential]


# ============================================================================
# Form Operation Configs
# ============================================================================


class TypeformListFormsConfig(BaseModel):
    """List all forms in your account"""

    operation: Literal["list_forms"] = Field(
        "list_forms",
        json_schema_extra={
            "const": "list_forms",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "List Forms",
        },
        title="List Forms",
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination (default: 1)"
    )
    page_size: Optional[int] = Field(
        10,
        title="Page Size",
        description="Number of forms per page (default: 10, max: 200)",
        ge=1,
        le=200,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter forms by title"
    )
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="Filter forms by workspace ID"
    )


class TypeformGetFormConfig(BaseModel):
    """Retrieve a specific form by ID"""

    operation: Literal["get_form"] = Field(
        "get_form",
        json_schema_extra={
            "const": "get_form",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Get Form",
        },
        title="Get Form",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformCreateFormConfig(BaseModel):
    """Create a new form"""

    operation: Literal["create_form"] = Field(
        "create_form",
        json_schema_extra={
            "const": "create_form",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Create Form",
            "x-creates-resource": True,
            "x-resource-type": "typeform_form",
            "x-resource-id-path": "id",
        },
        title="Create Form",
    )
    title: str = Field(..., title="Title", description="Title of the form")
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="ID of workspace to create form in"
    )
    fields: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Fields",
        description="Array of field definitions for the form",
        json_schema_extra={"ui:widget": "textarea"},
    )
    settings: Optional[Dict[str, Any]] = Field(
        None,
        title="Settings",
        description="Form settings (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    theme_id: Optional[str] = Field(
        None, title="Theme ID", description="ID of theme to apply to the form"
    )


class TypeformUpdateFormConfig(BaseModel):
    """Update an existing form"""

    operation: Literal["update_form"] = Field(
        "update_form",
        json_schema_extra={
            "const": "update_form",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Update Form",
        },
        title="Update Form",
    )
    form_id: str = Field(
        ..., title="Form ID", description="The unique ID of the form to update"
    )
    title: Optional[str] = Field(
        None, title="Title", description="New title for the form"
    )
    fields: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Fields",
        description="Updated array of field definitions",
        json_schema_extra={"ui:widget": "textarea"},
    )
    settings: Optional[Dict[str, Any]] = Field(
        None,
        title="Settings",
        description="Updated form settings (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    theme_id: Optional[str] = Field(
        None, title="Theme ID", description="ID of theme to apply to the form"
    )
    patch: Optional[bool] = Field(
        True,
        title="Partial Update",
        description="If true, only updates specified fields (PATCH). If false, replaces entire form (PUT)",
    )


class TypeformDeleteFormConfig(BaseModel):
    """Delete a form"""

    operation: Literal["delete_form"] = Field(
        "delete_form",
        json_schema_extra={
            "const": "delete_form",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Delete Form",
        },
        title="Delete Form",
    )
    form_id: str = Field(
        ..., title="Form ID", description="The unique ID of the form to delete"
    )


class TypeformGetFormMessagesConfig(BaseModel):
    """Retrieve custom messages for a form"""

    operation: Literal["get_form_custom_messages"] = Field(
        "get_form_custom_messages",
        json_schema_extra={
            "const": "get_form_custom_messages",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Get Form Custom Messages",
        },
        title="Get Form Custom Messages",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformUpdateFormMessagesConfig(BaseModel):
    """Update custom messages for a form"""

    operation: Literal["update_form_custom_messages"] = Field(
        "update_form_custom_messages",
        json_schema_extra={
            "const": "update_form_custom_messages",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Update Form Custom Messages",
        },
        title="Update Form Custom Messages",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    messages: Dict[str, Any] = Field(
        ...,
        title="Messages",
        description="Custom messages object (JSON)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Theme Operation Configs
# ============================================================================


class TypeformListThemesConfig(BaseModel):
    """List all themes in your account"""

    operation: Literal["list_themes"] = Field(
        "list_themes",
        json_schema_extra={
            "const": "list_themes",
            "ui:hidden": True,
            "x-category": "Theme",
            "x-is-trigger": False,
            "x-display-name": "List Themes",
        },
        title="List Themes",
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination (default: 1)"
    )
    page_size: Optional[int] = Field(
        10,
        title="Page Size",
        description="Number of themes per page (default: 10, max: 200)",
        ge=1,
        le=200,
    )


class TypeformGetThemeConfig(BaseModel):
    """Retrieve a specific theme by ID"""

    operation: Literal["get_theme"] = Field(
        "get_theme",
        json_schema_extra={
            "const": "get_theme",
            "ui:hidden": True,
            "x-category": "Theme",
            "x-is-trigger": False,
            "x-display-name": "Get Theme",
        },
        title="Get Theme",
    )
    theme_id: str = Field(
        ..., title="Theme ID", description="The unique ID of the theme"
    )


class TypeformCreateThemeConfig(BaseModel):
    """Create a new theme"""

    operation: Literal["create_theme"] = Field(
        "create_theme",
        json_schema_extra={
            "const": "create_theme",
            "ui:hidden": True,
            "x-category": "Theme",
            "x-is-trigger": False,
            "x-display-name": "Create Theme",
        },
        title="Create Theme",
    )
    name: str = Field(..., title="Name", description="Name of the theme")
    colors: Optional[Dict[str, str]] = Field(
        None,
        title="Colors",
        description="Color definitions (JSON object with question, answer, button, background keys)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    font: Optional[str] = Field(
        None, title="Font", description="Font family for the theme"
    )
    has_transparent_button: Optional[bool] = Field(
        None,
        title="Transparent Button",
        description="Whether to use transparent buttons",
    )


class TypeformUpdateThemeConfig(BaseModel):
    """Update an existing theme"""

    operation: Literal["update_theme"] = Field(
        "update_theme",
        json_schema_extra={
            "const": "update_theme",
            "ui:hidden": True,
            "x-category": "Theme",
            "x-is-trigger": False,
            "x-display-name": "Update Theme",
        },
        title="Update Theme",
    )
    theme_id: str = Field(
        ..., title="Theme ID", description="The unique ID of the theme to update"
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the theme"
    )
    colors: Optional[Dict[str, str]] = Field(
        None,
        title="Colors",
        description="Updated color definitions (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    font: Optional[str] = Field(None, title="Font", description="Updated font family")
    has_transparent_button: Optional[bool] = Field(
        None,
        title="Transparent Button",
        description="Whether to use transparent buttons",
    )
    patch: Optional[bool] = Field(
        True,
        title="Partial Update",
        description="If true, only updates specified fields (PATCH). If false, replaces entire theme (PUT)",
    )


class TypeformDeleteThemeConfig(BaseModel):
    """Delete a theme"""

    operation: Literal["delete_theme"] = Field(
        "delete_theme",
        json_schema_extra={
            "const": "delete_theme",
            "ui:hidden": True,
            "x-category": "Theme",
            "x-is-trigger": False,
            "x-display-name": "Delete Theme",
        },
        title="Delete Theme",
    )
    theme_id: str = Field(
        ..., title="Theme ID", description="The unique ID of the theme to delete"
    )


# ============================================================================
# Image Operation Configs
# ============================================================================


class TypeformListImagesConfig(BaseModel):
    """List all images in your account"""

    operation: Literal["list_images"] = Field(
        "list_images",
        json_schema_extra={
            "const": "list_images",
            "ui:hidden": True,
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "List Images",
        },
        title="List Images",
    )


class TypeformGetImageConfig(BaseModel):
    """Retrieve a specific image by ID"""

    operation: Literal["get_image"] = Field(
        "get_image",
        json_schema_extra={
            "const": "get_image",
            "ui:hidden": True,
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Get Image",
        },
        title="Get Image",
    )
    image_id: str = Field(
        ..., title="Image ID", description="The unique ID of the image"
    )
    size: Optional[
        Literal["default", "thumbnail", "mobile", "tablet", "choice", "background"]
    ] = Field("default", title="Size", description="Size variant to retrieve")


class TypeformCreateImageConfig(BaseModel):
    """Upload a new image"""

    operation: Literal["upload_image"] = Field(
        "upload_image",
        json_schema_extra={
            "const": "upload_image",
            "ui:hidden": True,
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Upload Image",
        },
        title="Upload Image",
    )
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    image_base64: Optional[str] = Field(
        None,
        title="Image Base64",
        description="Base64-encoded image data",
        json_schema_extra={"ui:widget": "textarea"},
    )
    file_name: Optional[str] = Field(
        None, title="File Name", description="Optional file name for the image"
    )


class TypeformDeleteImageConfig(BaseModel):
    """Delete an image"""

    operation: Literal["delete_image"] = Field(
        "delete_image",
        json_schema_extra={
            "const": "delete_image",
            "ui:hidden": True,
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Delete Image",
        },
        title="Delete Image",
    )
    image_id: str = Field(
        ..., title="Image ID", description="The unique ID of the image to delete"
    )


# ============================================================================
# Video Operation Configs
# ============================================================================


class TypeformUploadVideoConfig(BaseModel):
    """Upload a video file"""

    operation: Literal["upload_video"] = Field(
        "upload_video",
        json_schema_extra={
            "const": "upload_video",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Upload Video",
        },
        title="Upload Video",
    )
    video_url: str = Field(
        ...,
        title="Video URL",
        description="The video to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    file_name: Optional[str] = Field(
        None, title="File Name", description="Optional file name for the video"
    )


# ============================================================================
# Workspace Operation Configs
# ============================================================================


class TypeformListWorkspacesConfig(BaseModel):
    """List all workspaces in your account"""

    operation: Literal["list_workspaces"] = Field(
        "list_workspaces",
        json_schema_extra={
            "const": "list_workspaces",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Workspaces",
        },
        title="List Workspaces",
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination (default: 1)"
    )
    page_size: Optional[int] = Field(
        10,
        title="Page Size",
        description="Number of workspaces per page (default: 10, max: 200)",
        ge=1,
        le=200,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter workspaces by name"
    )


class TypeformGetWorkspaceConfig(BaseModel):
    """Retrieve a specific workspace by ID"""

    operation: Literal["get_workspace"] = Field(
        "get_workspace",
        json_schema_extra={
            "const": "get_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace",
        },
        title="Get Workspace",
    )
    workspace_id: str = Field(
        ..., title="Workspace ID", description="The unique ID of the workspace"
    )


class TypeformCreateWorkspaceConfig(BaseModel):
    """Create a new workspace"""

    operation: Literal["create_workspace"] = Field(
        "create_workspace",
        json_schema_extra={
            "const": "create_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Create Workspace",
        },
        title="Create Workspace",
    )
    name: str = Field(..., title="Name", description="Name of the workspace")


class TypeformUpdateWorkspaceConfig(BaseModel):
    """Update an existing workspace"""

    operation: Literal["update_workspace"] = Field(
        "update_workspace",
        json_schema_extra={
            "const": "update_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Update Workspace",
        },
        title="Update Workspace",
    )
    workspace_id: str = Field(
        ...,
        title="Workspace ID",
        description="The unique ID of the workspace to update",
    )
    name: str = Field(..., title="Name", description="New name for the workspace")


class TypeformDeleteWorkspaceConfig(BaseModel):
    """Delete a workspace"""

    operation: Literal["delete_workspace"] = Field(
        "delete_workspace",
        json_schema_extra={
            "const": "delete_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Delete Workspace",
        },
        title="Delete Workspace",
    )
    workspace_id: str = Field(
        ...,
        title="Workspace ID",
        description="The unique ID of the workspace to delete",
    )


class TypeformListAccountWorkspacesConfig(BaseModel):
    """List all account workspaces (organization level)"""

    operation: Literal["list_account_workspaces"] = Field(
        "list_account_workspaces",
        json_schema_extra={
            "const": "list_account_workspaces",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Account Workspaces",
        },
        title="List Account Workspaces",
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination (default: 1)"
    )
    page_size: Optional[int] = Field(
        10,
        title="Page Size",
        description="Number of workspaces per page (default: 10, max: 200)",
        ge=1,
        le=200,
    )


class TypeformCreateAccountWorkspaceConfig(BaseModel):
    """Create a new account workspace"""

    operation: Literal["create_account_workspace"] = Field(
        "create_account_workspace",
        json_schema_extra={
            "const": "create_account_workspace",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Create Account Workspace",
        },
        title="Create Account Workspace",
    )
    name: str = Field(..., title="Name", description="Name of the account workspace")


# ============================================================================
# Response Operation Configs
# ============================================================================


class TypeformGetResponsesConfig(BaseModel):
    """Retrieve responses for a form"""

    operation: Literal["get_form_responses"] = Field(
        "get_form_responses",
        json_schema_extra={
            "const": "get_form_responses",
            "ui:hidden": True,
            "x-category": "Form Response",
            "x-is-trigger": False,
            "x-display-name": "Get Form Responses",
        },
        title="Get Form Responses",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Number of responses per page (default: 25, max: 1000)",
        ge=1,
        le=1000,
    )
    since: Optional[str] = Field(
        None,
        title="Since",
        description="Retrieve responses after this date/time (ISO 8601 format)",
    )
    until: Optional[str] = Field(
        None,
        title="Until",
        description="Retrieve responses before this date/time (ISO 8601 format)",
    )
    after: Optional[str] = Field(
        None,
        title="After",
        description="Retrieve responses after this token (for pagination)",
    )
    before: Optional[str] = Field(
        None,
        title="Before",
        description="Retrieve responses before this token (for pagination)",
    )
    included_response_ids: Optional[str] = Field(
        None,
        title="Included Response IDs",
        description="Comma-separated list of response IDs to include",
    )
    completed: Optional[bool] = Field(
        None,
        title="Completed Only",
        description="If true, return only completed responses",
    )
    sort: Optional[Literal["submitted_at,asc", "submitted_at,desc"]] = Field(
        "submitted_at,desc", title="Sort", description="Sort order for responses"
    )
    query: Optional[str] = Field(
        None, title="Query", description="Query string to filter responses"
    )
    fields: Optional[str] = Field(
        None,
        title="Fields",
        description="Comma-separated list of fields to include in response",
    )


class TypeformDeleteResponsesConfig(BaseModel):
    """Delete responses from a form"""

    operation: Literal["delete_form_responses"] = Field(
        "delete_form_responses",
        json_schema_extra={
            "const": "delete_form_responses",
            "ui:hidden": True,
            "x-category": "Form Response",
            "x-is-trigger": False,
            "x-display-name": "Delete Form Responses",
        },
        title="Delete Form Responses",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    included_tokens: str = Field(
        ...,
        title="Response Tokens",
        description="Comma-separated list of response tokens to delete",
    )


class TypeformGetInsightsConfig(BaseModel):
    """Retrieve insights for a form"""

    operation: Literal["get_form_insights"] = Field(
        "get_form_insights",
        json_schema_extra={
            "const": "get_form_insights",
            "ui:hidden": True,
            "x-category": "Form Insights",
            "x-is-trigger": False,
            "x-display-name": "Get Form Insights",
        },
        title="Get Form Insights",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformDownloadFilesConfig(BaseModel):
    """Download all files uploaded in form responses"""

    operation: Literal["download_response_files"] = Field(
        "download_response_files",
        json_schema_extra={
            "const": "download_response_files",
            "ui:hidden": True,
            "x-category": "Form Response",
            "x-is-trigger": False,
            "x-display-name": "Download Response Files",
        },
        title="Download Response Files",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformGetFileFromResponseConfig(BaseModel):
    """Get a specific file from a response"""

    operation: Literal["get_response_file"] = Field(
        "get_response_file",
        json_schema_extra={
            "const": "get_response_file",
            "ui:hidden": True,
            "x-category": "Form Response",
            "x-is-trigger": False,
            "x-display-name": "Get Response File",
        },
        title="Get Response File",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    response_id: str = Field(
        ..., title="Response ID", description="The unique ID of the response"
    )
    field_id: str = Field(
        ..., title="Field ID", description="The unique ID of the file upload field"
    )
    filename: str = Field(
        ..., title="Filename", description="Name of the file to download"
    )


class TypeformRequestAudioMasterConfig(BaseModel):
    """Request generation of audio master file"""

    operation: Literal["request_audio_master_generation"] = Field(
        "request_audio_master_generation",
        json_schema_extra={
            "const": "request_audio_master_generation",
            "ui:hidden": True,
            "x-category": "Audio and Video Master",
            "x-is-trigger": False,
            "x-display-name": "Request Audio Master Generation",
        },
        title="Request Audio Master Generation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformGetAudioMasterConfig(BaseModel):
    """Get generated audio master file"""

    operation: Literal["get_generated_audio_master"] = Field(
        "get_generated_audio_master",
        json_schema_extra={
            "const": "get_generated_audio_master",
            "ui:hidden": True,
            "x-category": "Audio and Video Master",
            "x-is-trigger": False,
            "x-display-name": "Get Generated Audio Master",
        },
        title="Get Generated Audio Master",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformRequestVideoMasterConfig(BaseModel):
    """Request generation of video master file"""

    operation: Literal["request_video_master_generation"] = Field(
        "request_video_master_generation",
        json_schema_extra={
            "const": "request_video_master_generation",
            "ui:hidden": True,
            "x-category": "Audio and Video Master",
            "x-is-trigger": False,
            "x-display-name": "Request Video Master Generation",
        },
        title="Request Video Master Generation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformGetVideoMasterConfig(BaseModel):
    """Get generated video master file"""

    operation: Literal["get_generated_video_master"] = Field(
        "get_generated_video_master",
        json_schema_extra={
            "const": "get_generated_video_master",
            "ui:hidden": True,
            "x-category": "Audio and Video Master",
            "x-is-trigger": False,
            "x-display-name": "Get Generated Video Master",
        },
        title="Get Generated Video Master",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


# ============================================================================
# Webhook Operation Configs
# ============================================================================


class TypeformCreateWebhookConfig(BaseModel):
    """Create or update a webhook for a form"""

    operation: Literal["create_form_webhook"] = Field(
        "create_form_webhook",
        json_schema_extra={
            "const": "create_form_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Form Webhook",
        },
        title="Create Form Webhook",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    tag: str = Field(..., title="Tag", description="Unique tag for this webhook")
    url: str = Field(
        ..., title="Webhook URL", description="URL to send webhook payloads to"
    )
    enabled: Optional[bool] = Field(
        True, title="Enabled", description="Whether the webhook is enabled"
    )
    secret: Optional[str] = Field(
        None,
        title="Secret",
        description="Secret for webhook signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    verify_ssl: Optional[bool] = Field(
        True, title="Verify SSL", description="Whether to verify SSL certificates"
    )


class TypeformDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    operation: Literal["delete_form_webhook"] = Field(
        "delete_form_webhook",
        json_schema_extra={
            "const": "delete_form_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Form Webhook",
        },
        title="Delete Form Webhook",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    tag: str = Field(..., title="Tag", description="Tag of the webhook to delete")


class TypeformListWebhooksConfig(BaseModel):
    """List all webhooks for a form"""

    operation: Literal["list_form_webhooks"] = Field(
        "list_form_webhooks",
        json_schema_extra={
            "const": "list_form_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Form Webhooks",
        },
        title="List Form Webhooks",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformGetWebhookConfig(BaseModel):
    """Get a specific webhook"""

    operation: Literal["get_form_webhook"] = Field(
        "get_form_webhook",
        json_schema_extra={
            "const": "get_form_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Form Webhook",
        },
        title="Get Form Webhook",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    tag: str = Field(..., title="Tag", description="Tag of the webhook to retrieve")


class TypeformUpdateWebhookConfig(BaseModel):
    """Update a webhook"""

    operation: Literal["update_form_webhook"] = Field(
        "update_form_webhook",
        json_schema_extra={
            "const": "update_form_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Form Webhook",
        },
        title="Update Form Webhook",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    tag: str = Field(..., title="Tag", description="Tag of the webhook to update")
    url: Optional[str] = Field(
        None, title="Webhook URL", description="URL to send webhook payloads to"
    )
    enabled: Optional[bool] = Field(
        None, title="Enabled", description="Whether the webhook is enabled"
    )
    secret: Optional[str] = Field(
        None,
        title="Secret",
        description="Secret for webhook signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    verify_ssl: Optional[bool] = Field(
        None, title="Verify SSL", description="Whether to verify SSL certificates"
    )


# ============================================================================
# Translation Operation Configs
# ============================================================================


class TypeformGetTranslationStatusesConfig(BaseModel):
    """Get translation statuses for a form"""

    operation: Literal["get_form_translation_statuses"] = Field(
        "get_form_translation_statuses",
        json_schema_extra={
            "const": "get_form_translation_statuses",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Get Form Translation Statuses",
        },
        title="Get Form Translation Statuses",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")


class TypeformGetTranslationConfig(BaseModel):
    """Get a specific translation for a form"""

    operation: Literal["get_form_translation"] = Field(
        "get_form_translation",
        json_schema_extra={
            "const": "get_form_translation",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Get Form Translation",
        },
        title="Get Form Translation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    language: str = Field(
        ..., title="Language Code", description="Language code (e.g., 'es', 'fr', 'de')"
    )


class TypeformCreateTranslationConfig(BaseModel):
    """Create or update a translation for a form"""

    operation: Literal["create_form_translation"] = Field(
        "create_form_translation",
        json_schema_extra={
            "const": "create_form_translation",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Create Form Translation",
        },
        title="Create Form Translation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    language: str = Field(
        ..., title="Language Code", description="Language code (e.g., 'es', 'fr', 'de')"
    )
    translation_data: Dict[str, Any] = Field(
        ...,
        title="Translation Data",
        description="Translation content (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TypeformUpdateTranslationConfig(BaseModel):
    """Update a translation for a form"""

    operation: Literal["update_form_translation"] = Field(
        "update_form_translation",
        json_schema_extra={
            "const": "update_form_translation",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Update Form Translation",
        },
        title="Update Form Translation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    language: str = Field(
        ..., title="Language Code", description="Language code (e.g., 'es', 'fr', 'de')"
    )
    translation_data: Dict[str, Any] = Field(
        ...,
        title="Translation Data",
        description="Translation content (JSON object) to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TypeformAutoTranslateConfig(BaseModel):
    """Auto-translate a form to a target language"""

    operation: Literal["auto_translate_form_to_language"] = Field(
        "auto_translate_form_to_language",
        json_schema_extra={
            "const": "auto_translate_form_to_language",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Auto Translate Form to Language",
        },
        title="Auto Translate Form to Language",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    target_language: str = Field(
        ...,
        title="Target Language",
        description="Target language code (e.g., 'es', 'fr', 'de')",
    )


class TypeformDeleteTranslationConfig(BaseModel):
    """Delete a translation for a form"""

    operation: Literal["delete_form_translation"] = Field(
        "delete_form_translation",
        json_schema_extra={
            "const": "delete_form_translation",
            "ui:hidden": True,
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Delete Form Translation",
        },
        title="Delete Form Translation",
    )
    form_id: str = Field(..., title="Form ID", description="The unique ID of the form")
    language: str = Field(
        ...,
        title="Language Code",
        description="Language code of translation to delete (e.g., 'es', 'fr', 'de')",
    )


# ============================================================================
# Trigger operation config
# ============================================================================


class TypeformOnNewResponseConfig(BaseModel):
    """Trigger: fires when a new response is submitted to a Typeform form."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_new_form_response"] = Field(
        default="on_new_form_response",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Form Response",
        },
        title="On New Form Response",
    )
    form_id: str = Field(
        ...,
        title="Form ID",
        description="The unique ID of the form to watch for new responses",
        json_schema_extra={
            "x-resource-type": "typeform_form",
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a form ID",
            }
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# ============================================================================
# Union of all operation configs
# ============================================================================

TypeformNodeConfig = Annotated[
    Union[
        # Form operations
        TypeformListFormsConfig,
        TypeformGetFormConfig,
        TypeformCreateFormConfig,
        TypeformUpdateFormConfig,
        TypeformDeleteFormConfig,
        TypeformGetFormMessagesConfig,
        TypeformUpdateFormMessagesConfig,
        # Theme operations
        TypeformListThemesConfig,
        TypeformGetThemeConfig,
        TypeformCreateThemeConfig,
        TypeformUpdateThemeConfig,
        TypeformDeleteThemeConfig,
        # Image operations
        TypeformListImagesConfig,
        TypeformGetImageConfig,
        TypeformCreateImageConfig,
        TypeformDeleteImageConfig,
        # Video operations
        TypeformUploadVideoConfig,
        # Workspace operations
        TypeformListWorkspacesConfig,
        TypeformGetWorkspaceConfig,
        TypeformCreateWorkspaceConfig,
        TypeformUpdateWorkspaceConfig,
        TypeformDeleteWorkspaceConfig,
        TypeformListAccountWorkspacesConfig,
        TypeformCreateAccountWorkspaceConfig,
        # Response operations
        TypeformGetResponsesConfig,
        TypeformDeleteResponsesConfig,
        TypeformGetInsightsConfig,
        TypeformDownloadFilesConfig,
        TypeformGetFileFromResponseConfig,
        TypeformRequestAudioMasterConfig,
        TypeformGetAudioMasterConfig,
        TypeformRequestVideoMasterConfig,
        TypeformGetVideoMasterConfig,
        # Webhook operations
        TypeformCreateWebhookConfig,
        TypeformDeleteWebhookConfig,
        TypeformListWebhooksConfig,
        TypeformGetWebhookConfig,
        TypeformUpdateWebhookConfig,
        # Translation operations
        TypeformGetTranslationStatusesConfig,
        TypeformGetTranslationConfig,
        TypeformCreateTranslationConfig,
        TypeformUpdateTranslationConfig,
        TypeformAutoTranslateConfig,
        TypeformDeleteTranslationConfig,
        # Trigger operations
        TypeformOnNewResponseConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config
# ============================================================================


class TypeformNodeFullConfig(NodeConfig[TypeformNodeConfig, TypeformCredential]):
    """Complete node configuration with operation config and credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class TypeformNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Typeform workflow node implementation"""

    edit_examples = [
        "List all forms and get metadata for a customer survey",
        "Create feedback form with multiple choice and text fields",
        "Get form responses and process them by completion date",
        "Retrieve insights and analytics for product survey",
        "Download all responses from subscription form as CSV",
        "Update form title and description based on feedback",
        "Create webhook to trigger automation on new form submission",
    ]

    scope_registry = TYPEFORM_SCOPES
    connection_evidence = ConnectionEvidence(
        field="form_id",
        noun="forms",
    )
    @classmethod
    def get_config_model(cls):
        return TypeformNodeFullConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic dropdown options for a field."""
        logger.info(f"[TypeformNode] load_field_options called: field={field_name}")
        if field_name == "form_id":
            return await cls._list_form_options(
                credential_data, page_token=page_token, search=search
            )
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_form_options(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List the user's Typeform forms for dropdown options.

        Typeform uses 1-based page-number pagination (no cursor token, no
        search parameter), so we encode the page number as the cursor string
        and let :func:`load_paginated_options` orchestrate accumulate-and-
        filter in search mode while preserving single-page behavior
        otherwise.
        """
        token = require_credential_token(
            _typeform_token_from_credential(credential_data),
            "Connect a Typeform account to load forms",
        )

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            page = int(cursor) if cursor else 1
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{TYPEFORM_API_BASE}/forms",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"page_size": 200, "page": page},
                )
                response.raise_for_status()
                data = response.json()
            options = [
                {"value": item.get("id"), "label": item.get("title") or item.get("id")}
                for item in (data.get("items") or [])
                if item.get("id")
            ]
            page_count = data.get("page_count")
            next_cursor = (
                str(page + 1) if page_count and page < page_count else None
            )
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label="TypeformNode._list_form_options",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Typeform node based on the selected action"""
        config = self.config
        if not config or not isinstance(config, TypeformNodeFullConfig):
            raise ValueError("Configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials required. Connect an account in the credentials tab."
            )

        # Get access token (refresh if OAuth and expired)
        access_token = await self._ensure_fresh_token(credentials)

        # Route to appropriate handler based on action
        action_config = config.config
        action = action_config.operation

        # Form operations
        if action == "list_forms":
            return await self._list_forms(action_config, access_token)
        elif action == "get_form":
            return await self._get_form(action_config, access_token)
        elif action == "create_form":
            return await self._create_form(action_config, access_token)
        elif action == "update_form":
            return await self._update_form(action_config, access_token)
        elif action == "delete_form":
            return await self._delete_form(action_config, access_token)
        elif action == "get_form_custom_messages":
            return await self._get_form_messages(action_config, access_token)
        elif action == "update_form_custom_messages":
            return await self._update_form_messages(action_config, access_token)

        # Theme operations
        elif action == "list_themes":
            return await self._list_themes(action_config, access_token)
        elif action == "get_theme":
            return await self._get_theme(action_config, access_token)
        elif action == "create_theme":
            return await self._create_theme(action_config, access_token)
        elif action == "update_theme":
            return await self._update_theme(action_config, access_token)
        elif action == "delete_theme":
            return await self._delete_theme(action_config, access_token)

        # Image operations
        elif action == "list_images":
            return await self._list_images(access_token)
        elif action == "get_image":
            return await self._get_image(action_config, access_token)
        elif action == "upload_image":
            return await self._create_image(action_config, access_token)
        elif action == "delete_image":
            return await self._delete_image(action_config, access_token)

        # Video operations
        elif action == "upload_video":
            return await self._upload_video(action_config, access_token)

        # Workspace operations
        elif action == "list_workspaces":
            return await self._list_workspaces(action_config, access_token)
        elif action == "get_workspace":
            return await self._get_workspace(action_config, access_token)
        elif action == "create_workspace":
            return await self._create_workspace(action_config, access_token)
        elif action == "update_workspace":
            return await self._update_workspace(action_config, access_token)
        elif action == "delete_workspace":
            return await self._delete_workspace(action_config, access_token)
        elif action == "list_account_workspaces":
            return await self._list_account_workspaces(action_config, access_token)
        elif action == "create_account_workspace":
            return await self._create_account_workspace(action_config, access_token)

        # Response operations
        elif action == "get_form_responses":
            return await self._get_responses(action_config, access_token)
        elif action == "delete_form_responses":
            return await self._delete_responses(action_config, access_token)
        elif action == "get_form_insights":
            return await self._get_insights(action_config, access_token)
        elif action == "download_response_files":
            return await self._download_files(action_config, access_token)
        elif action == "get_response_file":
            return await self._get_file_from_response(action_config, access_token)
        elif action == "request_audio_master_generation":
            return await self._request_audio_master(action_config, access_token)
        elif action == "get_generated_audio_master":
            return await self._get_audio_master(action_config, access_token)
        elif action == "request_video_master_generation":
            return await self._request_video_master(action_config, access_token)
        elif action == "get_generated_video_master":
            return await self._get_video_master(action_config, access_token)

        # Webhook operations
        elif action == "create_form_webhook":
            return await self._create_webhook(action_config, access_token)
        elif action == "delete_form_webhook":
            return await self._delete_webhook(action_config, access_token)
        elif action == "list_form_webhooks":
            return await self._list_webhooks(action_config, access_token)
        elif action == "get_form_webhook":
            return await self._get_webhook(action_config, access_token)
        elif action == "update_form_webhook":
            return await self._update_webhook(action_config, access_token)

        # Translation operations
        elif action == "get_form_translation_statuses":
            return await self._get_translation_statuses(action_config, access_token)
        elif action == "get_form_translation":
            return await self._get_translation(action_config, access_token)
        elif action == "create_form_translation":
            return await self._create_translation(action_config, access_token)
        elif action == "update_form_translation":
            return await self._update_translation(action_config, access_token)
        elif action == "auto_translate_form_to_language":
            return await self._auto_translate(action_config, access_token)
        elif action == "delete_form_translation":
            return await self._delete_translation(action_config, access_token)

        # Trigger operations
        elif action == "on_new_form_response":
            return self._trigger_on_new_response(action_config)

        raise ValueError(f"Unknown action: {action}")

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Typeform OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating personal access tokens."""
        from nodes.core.oauth_refresh import freshen_oauth_credential

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="typeform",
        )

    async def _ensure_fresh_token(self, credentials: TypeformCredential) -> str:
        """Get access token, refreshing if necessary for OAuth credentials"""
        if isinstance(credentials, TypeformPATCredential):
            return credentials.personal_access_token

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="typeform",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    def _get_headers(self, token: str) -> Dict[str, str]:
        """Get HTTP headers for Typeform API requests"""
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to Typeform API with rate limiting"""
        url = f"{TYPEFORM_API_BASE}{endpoint}"
        headers = self._get_headers(token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_data
            )

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 1))
                logger.warning(f"Rate limited, waiting {retry_after} seconds...")
                time.sleep(retry_after)
                # Retry once
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                )

            response.raise_for_status()

            # Return empty dict for 204 No Content
            if response.status_code == 204:
                return {"success": True, "status_code": 204}

            return response.json()

    # ========================================================================
    # Form Operations
    # ========================================================================

    async def _list_forms(
        self, config: TypeformListFormsConfig, token: str
    ) -> Dict[str, Any]:
        """List all forms"""
        params = {"page": config.page, "page_size": config.page_size}
        if config.search:
            params["search"] = config.search
        if config.workspace_id:
            params["workspace_id"] = config.workspace_id

        return await self._make_request("GET", "/forms", token, params=params)

    async def _get_form(
        self, config: TypeformGetFormConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific form"""
        return await self._make_request("GET", f"/forms/{config.form_id}", token)

    async def _create_form(
        self, config: TypeformCreateFormConfig, token: str
    ) -> Dict[str, Any]:
        """Create a new form"""
        data = {"title": config.title}
        if config.workspace_id:
            data["workspace"] = {
                "href": f"{TYPEFORM_API_BASE}/workspaces/{config.workspace_id}"
            }
        if config.fields:
            data["fields"] = config.fields
        if config.settings:
            data["settings"] = config.settings
        if config.theme_id:
            data["theme"] = {"href": f"{TYPEFORM_API_BASE}/themes/{config.theme_id}"}

        return await self._make_request("POST", "/forms", token, json_data=data)

    async def _update_form(
        self, config: TypeformUpdateFormConfig, token: str
    ) -> Dict[str, Any]:
        """Update an existing form"""
        data = {}
        if config.title:
            data["title"] = config.title
        if config.fields is not None:
            data["fields"] = config.fields
        if config.settings is not None:
            data["settings"] = config.settings
        if config.theme_id:
            data["theme"] = {"href": f"{TYPEFORM_API_BASE}/themes/{config.theme_id}"}

        method = "PATCH" if config.patch else "PUT"
        return await self._make_request(
            method, f"/forms/{config.form_id}", token, json_data=data
        )

    async def _delete_form(
        self, config: TypeformDeleteFormConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a form"""
        return await self._make_request("DELETE", f"/forms/{config.form_id}", token)

    async def _get_form_messages(
        self, config: TypeformGetFormMessagesConfig, token: str
    ) -> Dict[str, Any]:
        """Get custom messages for a form"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/messages", token
        )

    async def _update_form_messages(
        self, config: TypeformUpdateFormMessagesConfig, token: str
    ) -> Dict[str, Any]:
        """Update custom messages for a form"""
        return await self._make_request(
            "PATCH",
            f"/forms/{config.form_id}/messages",
            token,
            json_data=config.messages,
        )

    # ========================================================================
    # Theme Operations
    # ========================================================================

    async def _list_themes(
        self, config: TypeformListThemesConfig, token: str
    ) -> Dict[str, Any]:
        """List all themes"""
        params = {"page": config.page, "page_size": config.page_size}
        return await self._make_request("GET", "/themes", token, params=params)

    async def _get_theme(
        self, config: TypeformGetThemeConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific theme"""
        return await self._make_request("GET", f"/themes/{config.theme_id}", token)

    async def _create_theme(
        self, config: TypeformCreateThemeConfig, token: str
    ) -> Dict[str, Any]:
        """Create a new theme"""
        data = {"name": config.name}
        if config.colors:
            data["colors"] = config.colors
        if config.font:
            data["font"] = config.font
        if config.has_transparent_button is not None:
            data["has_transparent_button"] = config.has_transparent_button

        return await self._make_request("POST", "/themes", token, json_data=data)

    async def _update_theme(
        self, config: TypeformUpdateThemeConfig, token: str
    ) -> Dict[str, Any]:
        """Update an existing theme"""
        data = {}
        if config.name:
            data["name"] = config.name
        if config.colors is not None:
            data["colors"] = config.colors
        if config.font:
            data["font"] = config.font
        if config.has_transparent_button is not None:
            data["has_transparent_button"] = config.has_transparent_button

        method = "PATCH" if config.patch else "PUT"
        return await self._make_request(
            method, f"/themes/{config.theme_id}", token, json_data=data
        )

    async def _delete_theme(
        self, config: TypeformDeleteThemeConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a theme"""
        return await self._make_request("DELETE", f"/themes/{config.theme_id}", token)

    # ========================================================================
    # Image Operations
    # ========================================================================

    async def _list_images(self, token: str) -> Dict[str, Any]:
        """List all images"""
        return await self._make_request("GET", "/images", token)

    async def _get_image(
        self, config: TypeformGetImageConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific image"""
        endpoint = f"/images/{config.image_id}"
        if config.size and config.size != "default":
            if config.size in ["background", "choice"]:
                endpoint = f"/images/{config.image_id}/{config.size}"
            else:
                endpoint = f"/images/{config.image_id}/sizes/{config.size}"

        return await self._make_request("GET", endpoint, token)

    async def _create_image(
        self, config: TypeformCreateImageConfig, token: str
    ) -> Dict[str, Any]:
        """Upload a new image"""
        data = {}
        if config.image_url:
            data["url"] = config.image_url
        if config.image_base64:
            data["image"] = config.image_base64
        if config.file_name:
            data["file_name"] = config.file_name

        return await self._make_request("POST", "/images", token, json_data=data)

    async def _delete_image(
        self, config: TypeformDeleteImageConfig, token: str
    ) -> Dict[str, Any]:
        """Delete an image"""
        return await self._make_request("DELETE", f"/images/{config.image_id}", token)

    # ========================================================================
    # Video Operations
    # ========================================================================

    async def _upload_video(
        self, config: TypeformUploadVideoConfig, token: str
    ) -> Dict[str, Any]:
        """Upload a video file"""
        data = {"url": config.video_url}
        if config.file_name:
            data["file_name"] = config.file_name

        return await self._make_request("POST", "/videos", token, json_data=data)

    # ========================================================================
    # Workspace Operations
    # ========================================================================

    async def _list_workspaces(
        self, config: TypeformListWorkspacesConfig, token: str
    ) -> Dict[str, Any]:
        """List all workspaces"""
        params = {"page": config.page, "page_size": config.page_size}
        if config.search:
            params["search"] = config.search

        return await self._make_request("GET", "/workspaces", token, params=params)

    async def _get_workspace(
        self, config: TypeformGetWorkspaceConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific workspace"""
        return await self._make_request(
            "GET", f"/workspaces/{config.workspace_id}", token
        )

    async def _create_workspace(
        self, config: TypeformCreateWorkspaceConfig, token: str
    ) -> Dict[str, Any]:
        """Create a new workspace"""
        data = {"name": config.name}
        return await self._make_request("POST", "/workspaces", token, json_data=data)

    async def _update_workspace(
        self, config: TypeformUpdateWorkspaceConfig, token: str
    ) -> Dict[str, Any]:
        """Update an existing workspace"""
        data = {"name": config.name}
        return await self._make_request(
            "PATCH", f"/workspaces/{config.workspace_id}", token, json_data=data
        )

    async def _delete_workspace(
        self, config: TypeformDeleteWorkspaceConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a workspace"""
        return await self._make_request(
            "DELETE", f"/workspaces/{config.workspace_id}", token
        )

    async def _list_account_workspaces(
        self, config: TypeformListAccountWorkspacesConfig, token: str
    ) -> Dict[str, Any]:
        """List all account-level workspaces"""
        params = {"page": config.page, "page_size": config.page_size}
        return await self._make_request(
            "GET", "/workspaces/account", token, params=params
        )

    async def _create_account_workspace(
        self, config: TypeformCreateAccountWorkspaceConfig, token: str
    ) -> Dict[str, Any]:
        """Create a new account workspace"""
        data = {"name": config.name}
        return await self._make_request(
            "POST", "/workspaces/account", token, json_data=data
        )

    # ========================================================================
    # Response Operations
    # ========================================================================

    async def _get_responses(
        self, config: TypeformGetResponsesConfig, token: str
    ) -> Dict[str, Any]:
        """Get responses for a form"""
        params = {"page_size": config.page_size}

        if config.since:
            params["since"] = config.since
        if config.until:
            params["until"] = config.until
        if config.after:
            params["after"] = config.after
        if config.before:
            params["before"] = config.before
        if config.included_response_ids:
            params["included_response_ids"] = config.included_response_ids
        if config.completed is not None:
            params["completed"] = str(config.completed).lower()
        if config.sort:
            params["sort"] = config.sort
        if config.query:
            params["query"] = config.query
        if config.fields:
            params["fields"] = config.fields

        return await self._make_request(
            "GET", f"/forms/{config.form_id}/responses", token, params=params
        )

    async def _delete_responses(
        self, config: TypeformDeleteResponsesConfig, token: str
    ) -> Dict[str, Any]:
        """Delete responses from a form"""
        params = {"included_tokens": config.included_tokens}
        return await self._make_request(
            "DELETE", f"/forms/{config.form_id}/responses", token, params=params
        )

    async def _get_insights(
        self, config: TypeformGetInsightsConfig, token: str
    ) -> Dict[str, Any]:
        """Get insights for a form"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/insights/summary", token
        )

    async def _download_files(
        self, config: TypeformDownloadFilesConfig, token: str
    ) -> Dict[str, Any]:
        """Download all files uploaded in form responses"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/responses/files", token
        )

    async def _get_file_from_response(
        self, config: TypeformGetFileFromResponseConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific file from a response"""
        return await self._make_request(
            "GET",
            f"/forms/{config.form_id}/responses/{config.response_id}/fields/{config.field_id}/files/{config.filename}",
            token,
        )

    async def _request_audio_master(
        self, config: TypeformRequestAudioMasterConfig, token: str
    ) -> Dict[str, Any]:
        """Request generation of audio master file"""
        return await self._make_request(
            "POST", f"/forms/{config.form_id}/responses/audio", token
        )

    async def _get_audio_master(
        self, config: TypeformGetAudioMasterConfig, token: str
    ) -> Dict[str, Any]:
        """Get generated audio master file"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/responses/audio", token
        )

    async def _request_video_master(
        self, config: TypeformRequestVideoMasterConfig, token: str
    ) -> Dict[str, Any]:
        """Request generation of video master file"""
        return await self._make_request(
            "POST", f"/forms/{config.form_id}/responses/video", token
        )

    async def _get_video_master(
        self, config: TypeformGetVideoMasterConfig, token: str
    ) -> Dict[str, Any]:
        """Get generated video master file"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/responses/video", token
        )

    # ========================================================================
    # Webhook Operations
    # ========================================================================

    async def _create_webhook(
        self, config: TypeformCreateWebhookConfig, token: str
    ) -> Dict[str, Any]:
        """Create or update a webhook"""
        data = {"url": config.url, "enabled": config.enabled}
        if config.secret:
            data["secret"] = config.secret
        if config.verify_ssl is not None:
            data["verify_ssl"] = config.verify_ssl

        return await self._make_request(
            "PUT",
            f"/forms/{config.form_id}/webhooks/{config.tag}",
            token,
            json_data=data,
        )

    async def _delete_webhook(
        self, config: TypeformDeleteWebhookConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a webhook"""
        return await self._make_request(
            "DELETE", f"/forms/{config.form_id}/webhooks/{config.tag}", token
        )

    async def _list_webhooks(
        self, config: TypeformListWebhooksConfig, token: str
    ) -> Dict[str, Any]:
        """List all webhooks for a form"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/webhooks", token
        )

    async def _get_webhook(
        self, config: TypeformGetWebhookConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific webhook"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/webhooks/{config.tag}", token
        )

    async def _update_webhook(
        self, config: TypeformUpdateWebhookConfig, token: str
    ) -> Dict[str, Any]:
        """Update a webhook"""
        data = {}
        if config.url is not None:
            data["url"] = config.url
        if config.enabled is not None:
            data["enabled"] = config.enabled
        if config.secret is not None:
            data["secret"] = config.secret
        if config.verify_ssl is not None:
            data["verify_ssl"] = config.verify_ssl

        return await self._make_request(
            "PATCH",
            f"/forms/{config.form_id}/webhooks/{config.tag}",
            token,
            json_data=data,
        )

    # ========================================================================
    # Webhook Trigger (on_new_form_response)
    # ========================================================================

    def _trigger_on_new_response(
        self, config: TypeformOnNewResponseConfig
    ) -> Dict[str, Any]:
        """Output when the trigger node is run manually from the editor.

        In a live workflow the node fires from a webhook delivery and outputs
        Typeform's response payload directly (the base ``resolve_trigger_payload``
        returns the payload unchanged).
        """
        return {
            "message": (
                "This trigger fires when a new response is submitted to the "
                "form. It outputs the Typeform response payload."
            ),
            "form_id": config.form_id,
        }

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "form_id": (config or {}).get("form_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls,
        *,
        webhook_url: str,
        credential: Dict[str, Any],
        config: Dict[str, Any],
        node_id: str,
    ) -> Dict[str, Any]:
        form_id = (config or {}).get("form_id")
        if not form_id:
            raise ValueError("Set a Form ID to activate this trigger")
        token = _typeform_token_from_credential(credential)
        if not token:
            raise ValueError("Typeform credential is missing an access token")
        secret = (config or {}).get("signing_secret") or secrets.token_hex(32)
        await register_typeform_webhook(
            token, form_id, _typeform_webhook_tag(node_id), webhook_url, secret
        )
        return {"signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(
        cls,
        *,
        credential: Optional[Dict[str, Any]],
        config: Dict[str, Any],
        node_id: str,
    ) -> None:
        form_id = (config or {}).get("form_id")
        token = _typeform_token_from_credential(credential or {})
        if not form_id or not token:
            return
        await unregister_typeform_webhook(
            token, form_id, _typeform_webhook_tag(node_id)
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Typeform's ``Typeform-Signature: sha256=<base64>`` header."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        header = headers.get("typeform-signature", "")
        if not header.startswith("sha256="):
            return False
        return verify_hmac_sha256_base64(
            body, secret, header[len("sha256=") :]
        )

    # ========================================================================
    # Translation Operations
    # ========================================================================

    async def _get_translation_statuses(
        self, config: TypeformGetTranslationStatusesConfig, token: str
    ) -> Dict[str, Any]:
        """Get translation statuses for a form"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/translations/statuses", token
        )

    async def _get_translation(
        self, config: TypeformGetTranslationConfig, token: str
    ) -> Dict[str, Any]:
        """Get a specific translation"""
        return await self._make_request(
            "GET", f"/forms/{config.form_id}/translations/{config.language}", token
        )

    async def _create_translation(
        self, config: TypeformCreateTranslationConfig, token: str
    ) -> Dict[str, Any]:
        """Create or update a translation"""
        return await self._make_request(
            "PUT",
            f"/forms/{config.form_id}/translations/{config.language}",
            token,
            json_data=config.translation_data,
        )

    async def _update_translation(
        self, config: TypeformUpdateTranslationConfig, token: str
    ) -> Dict[str, Any]:
        """Update an existing translation"""
        return await self._make_request(
            "PUT",
            f"/forms/{config.form_id}/translations/{config.language}",
            token,
            json_data=config.translation_data,
        )

    async def _auto_translate(
        self, config: TypeformAutoTranslateConfig, token: str
    ) -> Dict[str, Any]:
        """Auto-translate a form"""
        data = {"target_language": config.target_language}
        return await self._make_request(
            "POST", f"/forms/{config.form_id}/translations/auto", token, json_data=data
        )

    async def _delete_translation(
        self, config: TypeformDeleteTranslationConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a translation"""
        return await self._make_request(
            "DELETE", f"/forms/{config.form_id}/translations/{config.language}", token
        )
