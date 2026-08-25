"""
Canva Connect API automation node.

Provides workflow integration with Canva Connect API supporting ALL 50 available operations.

Categories:
- Design Operations (5): list, create, get, list pages, get export formats
- Asset Operations (7): upload from URL/binary, get, update, delete, get upload job status
- Export Operations (2): create export job, get export status
- Folder Operations (6): create, get, update, delete, list items, move items
- User Operations (3): get current user, get profile, get capabilities
- Resize Operations (2 - GA): create resize job, get resize status
- Design Import Operations (4): import from URL/binary, get import job status
- Brand Template Operations (3 - Preview): list templates, get template, get dataset
- Autofill Operations (2 - Preview): create autofill job, get autofill status
- Comment Operations (5 - Preview): create thread, get thread, create reply, list replies, get reply
- OAuth Token Management (2): introspect token, revoke token
- Connect API (1): get webhook verification keys
- OIDC Operations (2): get JWKS, get user info
- App JWT Operations (1): get app JWKS

Authentication: OAuth 2.0 with PKCE
API Base URL: https://api.canva.com/rest
Documentation: https://www.canva.dev/docs/connect/
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.canva_oauth import is_token_expired, refresh_access_token
from nodes.scopes.content_storage import CANVA_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

CANVA_API_BASE = "https://api.canva.com/rest"

# ============================================================================
# Credential Schema
# ============================================================================


class CanvaOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Canva.
    Tokens are obtained via OAuth flow with PKCE, not entered manually.

    Documentation: https://www.canva.dev/docs/connect/authentication/
    """

    credential_type: Literal["canva_oauth"] = Field(
        "canva_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Canva"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    display_name: Optional[str] = Field(
        None,
        title="Display Name",
        description="Display name of the connected Canva account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "canva",
        # Temporary: Canva's OAuth app is awaiting Canva's review. Remove this
        # notice once the integration is approved and connecting is enabled.
        "x-credential-notice": (
            "The Canva integration is currently unavailable while its OAuth app "
            "awaits approval from Canva. You'll be able to connect once it's approved."
        ),
        "x-oauth-scopes": [
            "asset:read",
            "asset:write",
            "design:meta:read",
            "design:content:read",
            "design:content:write",
            "folder:read",
            "folder:write",
            "profile:read",
            "brandtemplate:meta:read",
            "brandtemplate:content:read",
            "comment:read",
            "comment:write",
        ],
    })


# ============================================================================
# Design Operation Configs
# ============================================================================


class CanvaListDesignsConfig(BaseModel):
    """List user's designs"""

    operation: Literal["list_user_designs"] = Field(
        "list_user_designs",
        json_schema_extra={
            "const": "list_user_designs",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "List User Designs",
        },
        title="List User Designs",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Search term to filter designs"
    )
    continuation: Optional[str] = Field(
        None,
        title="Continuation Token",
        description="Pagination token from previous response",
    )
    ownership: Optional[Literal["owned", "shared", "any"]] = Field(
        "any", title="Ownership", description="Filter by ownership type"
    )

    model_config = ConfigDict(title="List Designs")


class CanvaCreateDesignConfig(BaseModel):
    """Create a new Canva design"""

    operation: Literal["create_design"] = Field(
        "create_design",
        json_schema_extra={
            "const": "create_design",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Create Design",
        },
        title="Create Design",
    )
    design_type: str = Field(
        ...,
        title="Design Type",
        description="Type of design to create (e.g., 'Presentation', 'Whiteboard', 'Doc')",
        json_schema_extra={
            "enum": [
                "Presentation",
                "Whiteboard",
                "Doc",
                "Instagram Post",
                "Instagram Story",
                "Facebook Post",
                "LinkedIn Post",
                "Twitter Post",
                "YouTube Thumbnail",
                "Poster",
                "Flyer",
                "A4 Document",
                "Letter Document",
                "Business Card",
                "Logo",
                "Infographic",
                "Resume",
            ]
        },
    )
    title: Optional[str] = Field(
        None, title="Title", description="Title for the new design"
    )
    asset_id: Optional[str] = Field(
        None,
        title="Asset ID",
        description="ID of an asset to use as the design's initial content",
    )

    model_config = ConfigDict(title="Create Design")


class CanvaGetDesignConfig(BaseModel):
    """Get design metadata"""

    operation: Literal["get_design_metadata"] = Field(
        "get_design_metadata",
        json_schema_extra={
            "const": "get_design_metadata",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Get Design Metadata",
        },
        title="Get Design Metadata",
    )
    design_id: str = Field(
        ..., title="Design ID", description="The ID of the design to retrieve"
    )

    model_config = ConfigDict(title="Get Design")


class CanvaListDesignPagesConfig(BaseModel):
    """List pages in a design (preview feature)"""

    operation: Literal["list_design_pages"] = Field(
        "list_design_pages",
        json_schema_extra={
            "const": "list_design_pages",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "List Design Pages",
        },
        title="List Design Pages",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")

    model_config = ConfigDict(title="List Design Pages")


class CanvaGetExportFormatsConfig(BaseModel):
    """Get available export formats for a design (preview feature)"""

    operation: Literal["get_design_export_formats"] = Field(
        "get_design_export_formats",
        json_schema_extra={
            "const": "get_design_export_formats",
            "ui:hidden": True,
            "x-category": "Design Export",
            "x-is-trigger": False,
            "x-display-name": "Get Design Export Formats",
        },
        title="Get Design Export Formats",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")

    model_config = ConfigDict(title="Get Export Formats")


# ============================================================================
# Asset Operation Configs
# ============================================================================


class CanvaUploadAssetFromURLConfig(BaseModel):
    """Upload an asset from a URL (preview feature)"""

    operation: Literal["upload_asset_from_url"] = Field(
        "upload_asset_from_url",
        json_schema_extra={
            "const": "upload_asset_from_url",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Upload Asset from Url",
        },
        title="Upload Asset from Url",
    )
    url: str = Field(..., title="URL", description="URL of the file to upload")
    name: Optional[str] = Field(
        None, title="Name", description="Name for the uploaded asset"
    )

    model_config = ConfigDict(title="Upload Asset from URL")


class CanvaGetAssetConfig(BaseModel):
    """Get asset metadata"""

    operation: Literal["get_asset_metadata"] = Field(
        "get_asset_metadata",
        json_schema_extra={
            "const": "get_asset_metadata",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Get Asset Metadata",
        },
        title="Get Asset Metadata",
    )
    asset_id: str = Field(
        ..., title="Asset ID", description="The ID of the asset to retrieve"
    )

    model_config = ConfigDict(title="Get Asset")


class CanvaUpdateAssetConfig(BaseModel):
    """Update asset name or tags"""

    operation: Literal["update_asset_name_or_tags"] = Field(
        "update_asset_name_or_tags",
        json_schema_extra={
            "const": "update_asset_name_or_tags",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Update Asset Name or Tags",
        },
        title="Update Asset Name or Tags",
    )
    asset_id: str = Field(
        ..., title="Asset ID", description="The ID of the asset to update"
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the asset"
    )
    tags: Optional[List[str]] = Field(
        None, title="Tags", description="New tags for the asset"
    )

    model_config = ConfigDict(title="Update Asset")


class CanvaDeleteAssetConfig(BaseModel):
    """Delete an asset"""

    operation: Literal["delete_asset"] = Field(
        "delete_asset",
        json_schema_extra={
            "const": "delete_asset",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Delete Asset",
        },
        title="Delete Asset",
    )
    asset_id: str = Field(
        ..., title="Asset ID", description="The ID of the asset to delete"
    )

    model_config = ConfigDict(title="Delete Asset")


class CanvaGetAssetUploadJobConfig(BaseModel):
    """Get status of an asset upload job"""

    operation: Literal["get_asset_upload_job_status"] = Field(
        "get_asset_upload_job_status",
        json_schema_extra={
            "const": "get_asset_upload_job_status",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Get Asset Upload Job Status",
        },
        title="Get Asset Upload Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the upload job")

    model_config = ConfigDict(title="Get Asset Upload Job")


# ============================================================================
# Export Operation Configs
# ============================================================================


class CanvaCreateExportConfig(BaseModel):
    """Create a design export job"""

    operation: Literal["create_design_export_job"] = Field(
        "create_design_export_job",
        json_schema_extra={
            "const": "create_design_export_job",
            "ui:hidden": True,
            "x-category": "Design Export",
            "x-is-trigger": False,
            "x-display-name": "Create Design Export Job",
        },
        title="Create Design Export Job",
    )
    design_id: str = Field(
        ..., title="Design ID", description="The ID of the design to export"
    )
    format: Literal["pdf", "jpg", "png", "gif", "pptx", "mp4"] = Field(
        ..., title="Export Format", description="Format to export the design as"
    )
    pages: Optional[List[int]] = Field(
        None,
        title="Pages",
        description="Specific page numbers to export (1-indexed). Leave empty for all pages.",
    )
    quality: Optional[Literal["regular", "pro"]] = Field(
        "regular", title="Quality", description="Export quality level"
    )
    lossless: Optional[bool] = Field(
        True,
        title="Lossless",
        description="For PNG exports, whether to use lossless compression",
    )

    model_config = ConfigDict(title="Create Export")


class CanvaGetExportJobConfig(BaseModel):
    """Get status of an export job"""

    operation: Literal["get_design_export_job_status"] = Field(
        "get_design_export_job_status",
        json_schema_extra={
            "const": "get_design_export_job_status",
            "ui:hidden": True,
            "x-category": "Design Export",
            "x-is-trigger": False,
            "x-display-name": "Get Design Export Job Status",
        },
        title="Get Design Export Job Status",
    )
    export_id: str = Field(
        ..., title="Export ID", description="The ID of the export job"
    )

    model_config = ConfigDict(title="Get Export Job")


# ============================================================================
# Folder Operation Configs
# ============================================================================


class CanvaCreateFolderConfig(BaseModel):
    """Create a new folder"""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
        },
        title="Create Folder",
    )
    name: str = Field(..., title="Folder Name", description="Name for the new folder")
    parent_folder_id: Optional[str] = Field(
        "root",
        title="Parent Folder ID",
        description="ID of the parent folder (use 'root' for top-level)",
    )

    model_config = ConfigDict(title="Create Folder")


class CanvaGetFolderConfig(BaseModel):
    """Get folder details"""

    operation: Literal["get_folder_details"] = Field(
        "get_folder_details",
        json_schema_extra={
            "const": "get_folder_details",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Folder Details",
        },
        title="Get Folder Details",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="The ID of the folder (use 'root' for Projects folder)",
    )

    model_config = ConfigDict(title="Get Folder")


class CanvaUpdateFolderConfig(BaseModel):
    """Update folder name"""

    operation: Literal["update_folder_name"] = Field(
        "update_folder_name",
        json_schema_extra={
            "const": "update_folder_name",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Update Folder Name",
        },
        title="Update Folder Name",
    )
    folder_id: str = Field(
        ..., title="Folder ID", description="The ID of the folder to update"
    )
    name: str = Field(..., title="Name", description="New name for the folder")

    model_config = ConfigDict(title="Update Folder")


class CanvaDeleteFolderConfig(BaseModel):
    """Delete a folder"""

    operation: Literal["delete_folder"] = Field(
        "delete_folder",
        json_schema_extra={
            "const": "delete_folder",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Delete Folder",
        },
        title="Delete Folder",
    )
    folder_id: str = Field(
        ..., title="Folder ID", description="The ID of the folder to delete"
    )

    model_config = ConfigDict(title="Delete Folder")


class CanvaListFolderItemsConfig(BaseModel):
    """List items in a folder"""

    operation: Literal["list_folder_contents"] = Field(
        "list_folder_contents",
        json_schema_extra={
            "const": "list_folder_contents",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "List Folder Contents",
        },
        title="List Folder Contents",
    )
    folder_id: str = Field(
        "root",
        title="Folder ID",
        description="The ID of the folder (use 'root' for Projects folder)",
    )
    item_types: Optional[List[Literal["design", "folder", "image"]]] = Field(
        None, title="Item Types", description="Filter by item types"
    )
    continuation: Optional[str] = Field(
        None,
        title="Continuation Token",
        description="Pagination token from previous response",
    )

    model_config = ConfigDict(title="List Folder Items")


class CanvaMoveItemConfig(BaseModel):
    """Move an item to a folder"""

    operation: Literal["move_item_to_folder"] = Field(
        "move_item_to_folder",
        json_schema_extra={
            "const": "move_item_to_folder",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Move Item to Folder",
        },
        title="Move Item to Folder",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="The ID of the item to move (design, folder, or asset)",
    )
    item_type: Literal["design", "folder", "asset"] = Field(
        ..., title="Item Type", description="The type of item being moved"
    )
    to_folder_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="The ID of the destination folder",
    )

    model_config = ConfigDict(title="Move Item")


# ============================================================================
# User Operation Configs
# ============================================================================


class CanvaGetUserConfig(BaseModel):
    """Get current user ID"""

    operation: Literal["get_current_user_id"] = Field(
        "get_current_user_id",
        json_schema_extra={
            "const": "get_current_user_id",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User Id",
        },
        title="Get Current User Id",
    )

    model_config = ConfigDict(title="Get User")


class CanvaGetUserProfileConfig(BaseModel):
    """Get user profile information"""

    operation: Literal["get_user_profile_information"] = Field(
        "get_user_profile_information",
        json_schema_extra={
            "const": "get_user_profile_information",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Profile Information",
        },
        title="Get User Profile Information",
    )

    model_config = ConfigDict(title="Get User Profile")


class CanvaGetUserCapabilitiesConfig(BaseModel):
    """Get user capabilities (what features are available)"""

    operation: Literal["get_user_available_features"] = Field(
        "get_user_available_features",
        json_schema_extra={
            "const": "get_user_available_features",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Available Features",
        },
        title="Get User Available Features",
    )

    model_config = ConfigDict(title="Get User Capabilities")


# ============================================================================
# Resize Operation Configs (GA - General Availability)
# ============================================================================


class CanvaCreateResizeConfig(BaseModel):
    """Create async job to resize a design to new dimensions"""

    operation: Literal["create_design_resize_job"] = Field(
        "create_design_resize_job",
        json_schema_extra={
            "const": "create_design_resize_job",
            "ui:hidden": True,
            "x-category": "Design Resize",
            "x-is-trigger": False,
            "x-display-name": "Create Design Resize Job",
        },
        title="Create Design Resize Job",
    )
    design_id: str = Field(
        ..., title="Design ID", description="The ID of the design to resize"
    )
    width: int = Field(..., title="Width (px)", description="Target width in pixels")
    height: int = Field(..., title="Height (px)", description="Target height in pixels")
    title: Optional[str] = Field(
        None, title="Title", description="Title for the resized design copy"
    )

    model_config = ConfigDict(title="Create Resize")


class CanvaGetResizeJobConfig(BaseModel):
    """Get status of a design resize job"""

    operation: Literal["get_design_resize_job_status"] = Field(
        "get_design_resize_job_status",
        json_schema_extra={
            "const": "get_design_resize_job_status",
            "ui:hidden": True,
            "x-category": "Design Resize",
            "x-is-trigger": False,
            "x-display-name": "Get Design Resize Job Status",
        },
        title="Get Design Resize Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the resize job")

    model_config = ConfigDict(title="Get Resize Job")


# ============================================================================
# Design Import Operation Configs
# ============================================================================


class CanvaImportFromURLConfig(BaseModel):
    """Import a file as a design from URL"""

    operation: Literal["import_design_from_url"] = Field(
        "import_design_from_url",
        json_schema_extra={
            "const": "import_design_from_url",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Import Design from Url",
        },
        title="Import Design from Url",
    )
    url: str = Field(
        ...,
        title="URL",
        description="URL of the file to import (supports PDF, PPT, PPTX, etc.)",
    )
    title: Optional[str] = Field(
        None, title="Title", description="Title for the imported design"
    )

    model_config = ConfigDict(title="Import from URL")


class CanvaGetImportJobConfig(BaseModel):
    """Get status of a design import job"""

    operation: Literal["get_design_import_job_status"] = Field(
        "get_design_import_job_status",
        json_schema_extra={
            "const": "get_design_import_job_status",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Get Design Import Job Status",
        },
        title="Get Design Import Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the import job")

    model_config = ConfigDict(title="Get Import Job")


# ============================================================================
# Binary Import Operation Configs
# ============================================================================


class CanvaCreateDesignImportConfig(BaseModel):
    """Import design from binary file data"""

    operation: Literal["import_design_from_binary_file"] = Field(
        "import_design_from_binary_file",
        json_schema_extra={
            "const": "import_design_from_binary_file",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Import Design from Binary File",
        },
        title="Import Design from Binary File",
    )
    file_data: str = Field(
        ..., title="File Data (Base64)", description="Base64-encoded binary file data"
    )
    title: Optional[str] = Field(
        None, title="Title", description="Title for the imported design"
    )

    model_config = ConfigDict(title="Create Design Import")


class CanvaGetDesignImportJobConfig(BaseModel):
    """Get status of binary design import job"""

    operation: Literal["get_binary_design_import_job_status"] = Field(
        "get_binary_design_import_job_status",
        json_schema_extra={
            "const": "get_binary_design_import_job_status",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Get Binary Design Import Job Status",
        },
        title="Get Binary Design Import Job Status",
    )
    job_id: str = Field(
        ..., title="Job ID", description="The ID of the design import job"
    )

    model_config = ConfigDict(title="Get Design Import Job")


# ============================================================================
# Binary Asset Upload Operation Configs
# ============================================================================


class CanvaCreateAssetUploadConfig(BaseModel):
    """Upload asset from binary data"""

    operation: Literal["upload_asset_from_binary"] = Field(
        "upload_asset_from_binary",
        json_schema_extra={
            "const": "upload_asset_from_binary",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Upload Asset from Binary",
        },
        title="Upload Asset from Binary",
    )
    file_data: str = Field(
        ...,
        title="File Data (Base64)",
        description="Base64-encoded binary file data (max 50MB for images)",
    )
    name: Optional[str] = Field(
        None, title="Asset Name", description="Name for the asset"
    )
    tags: Optional[List[str]] = Field(
        None, title="Tags", description="Tags to organize the asset"
    )

    model_config = ConfigDict(title="Create Asset Upload")


class CanvaGetAssetUploadJobStatusConfig(BaseModel):
    """Get status of binary asset upload job"""

    operation: Literal["get_binary_asset_upload_job_status"] = Field(
        "get_binary_asset_upload_job_status",
        json_schema_extra={
            "const": "get_binary_asset_upload_job_status",
            "ui:hidden": True,
            "x-category": "Asset",
            "x-is-trigger": False,
            "x-display-name": "Get Binary Asset Upload Job Status",
        },
        title="Get Binary Asset Upload Job Status",
    )
    job_id: str = Field(
        ..., title="Job ID", description="The ID of the asset upload job"
    )

    model_config = ConfigDict(title="Get Asset Upload Job Status")


# ============================================================================
# Brand Template Operation Configs (Preview)
# ============================================================================


class CanvaListBrandTemplatesConfig(BaseModel):
    """List brand templates with search and filters"""

    operation: Literal["list_brand_templates_with_search"] = Field(
        "list_brand_templates_with_search",
        json_schema_extra={
            "const": "list_brand_templates_with_search",
            "ui:hidden": True,
            "x-category": "Brand Template",
            "x-is-trigger": False,
            "x-display-name": "List Brand Templates with Search",
        },
        title="List Brand Templates with Search",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Search term to filter brand templates"
    )
    continuation: Optional[str] = Field(
        None,
        title="Continuation Token",
        description="Pagination token from previous response",
    )

    model_config = ConfigDict(title="List Brand Templates")


class CanvaGetBrandTemplateConfig(BaseModel):
    """Get brand template metadata"""

    operation: Literal["get_brand_template_metadata"] = Field(
        "get_brand_template_metadata",
        json_schema_extra={
            "const": "get_brand_template_metadata",
            "ui:hidden": True,
            "x-category": "Brand Template",
            "x-is-trigger": False,
            "x-display-name": "Get Brand Template Metadata",
        },
        title="Get Brand Template Metadata",
    )
    brand_template_id: str = Field(
        ..., title="Brand Template ID", description="The ID of the brand template"
    )

    model_config = ConfigDict(title="Get Brand Template")


class CanvaGetBrandTemplateDatasetConfig(BaseModel):
    """Get dataset definition for autofill fields"""

    operation: Literal["get_autofill_dataset_definition"] = Field(
        "get_autofill_dataset_definition",
        json_schema_extra={
            "const": "get_autofill_dataset_definition",
            "ui:hidden": True,
            "x-category": "Design Autofill",
            "x-is-trigger": False,
            "x-display-name": "Get Autofill Dataset Definition",
        },
        title="Get Autofill Dataset Definition",
    )
    brand_template_id: str = Field(
        ..., title="Brand Template ID", description="The ID of the brand template"
    )

    model_config = ConfigDict(title="Get Brand Template Dataset")


# ============================================================================
# Autofill Operation Configs (Preview)
# ============================================================================


class CanvaCreateAutofillJobConfig(BaseModel):
    """Start async job to autofill design using brand template"""

    operation: Literal["create_design_autofill_job"] = Field(
        "create_design_autofill_job",
        json_schema_extra={
            "const": "create_design_autofill_job",
            "ui:hidden": True,
            "x-category": "Design Autofill",
            "x-is-trigger": False,
            "x-display-name": "Create Design Autofill Job",
        },
        title="Create Design Autofill Job",
    )
    brand_template_id: str = Field(
        ...,
        title="Brand Template ID",
        description="The ID of the brand template to use",
    )
    data: Dict[str, Any] = Field(
        ..., title="Data", description="Data to autofill into the template fields"
    )
    title: Optional[str] = Field(
        None, title="Title", description="Title for the autofilled design"
    )

    model_config = ConfigDict(title="Create Autofill Job")


class CanvaGetAutofillJobConfig(BaseModel):
    """Get status of design autofill job"""

    operation: Literal["get_design_autofill_job_status"] = Field(
        "get_design_autofill_job_status",
        json_schema_extra={
            "const": "get_design_autofill_job_status",
            "ui:hidden": True,
            "x-category": "Design Autofill",
            "x-is-trigger": False,
            "x-display-name": "Get Design Autofill Job Status",
        },
        title="Get Design Autofill Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the autofill job")

    model_config = ConfigDict(title="Get Autofill Job")


# ============================================================================
# Comment Operation Configs (Preview)
# ============================================================================


class CanvaCreateCommentThreadConfig(BaseModel):
    """Create comment thread on design"""

    operation: Literal["create_design_comment_thread"] = Field(
        "create_design_comment_thread",
        json_schema_extra={
            "const": "create_design_comment_thread",
            "ui:hidden": True,
            "x-category": "Comment Thread",
            "x-is-trigger": False,
            "x-display-name": "Create Design Comment Thread",
        },
        title="Create Design Comment Thread",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")
    message: str = Field(..., title="Message", description="Comment message content")

    model_config = ConfigDict(title="Create Comment Thread")


class CanvaGetCommentThreadConfig(BaseModel):
    """Get comment or suggestion thread"""

    operation: Literal["get_design_comment_thread"] = Field(
        "get_design_comment_thread",
        json_schema_extra={
            "const": "get_design_comment_thread",
            "ui:hidden": True,
            "x-category": "Comment Thread",
            "x-is-trigger": False,
            "x-display-name": "Get Design Comment Thread",
        },
        title="Get Design Comment Thread",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")
    thread_id: str = Field(
        ..., title="Thread ID", description="The ID of the comment thread"
    )

    model_config = ConfigDict(title="Get Comment Thread")


class CanvaCreateReplyConfig(BaseModel):
    """Create reply to comment thread"""

    operation: Literal["create_comment_thread_reply"] = Field(
        "create_comment_thread_reply",
        json_schema_extra={
            "const": "create_comment_thread_reply",
            "ui:hidden": True,
            "x-category": "Comment Thread",
            "x-is-trigger": False,
            "x-display-name": "Create Comment Thread Reply",
        },
        title="Create Comment Thread Reply",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")
    thread_id: str = Field(
        ..., title="Thread ID", description="The ID of the comment thread"
    )
    message: str = Field(..., title="Message", description="Reply message content")

    model_config = ConfigDict(title="Create Reply")


class CanvaListRepliesConfig(BaseModel):
    """List replies for a comment thread"""

    operation: Literal["list_comment_thread_replies"] = Field(
        "list_comment_thread_replies",
        json_schema_extra={
            "const": "list_comment_thread_replies",
            "ui:hidden": True,
            "x-category": "Comment Thread",
            "x-is-trigger": False,
            "x-display-name": "List Comment Thread Replies",
        },
        title="List Comment Thread Replies",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")
    thread_id: str = Field(
        ..., title="Thread ID", description="The ID of the comment thread"
    )

    model_config = ConfigDict(title="List Replies")


class CanvaGetReplyConfig(BaseModel):
    """Get specific reply from thread"""

    operation: Literal["get_comment_thread_reply"] = Field(
        "get_comment_thread_reply",
        json_schema_extra={
            "const": "get_comment_thread_reply",
            "ui:hidden": True,
            "x-category": "Comment Thread",
            "x-is-trigger": False,
            "x-display-name": "Get Comment Thread Reply",
        },
        title="Get Comment Thread Reply",
    )
    design_id: str = Field(..., title="Design ID", description="The ID of the design")
    thread_id: str = Field(
        ..., title="Thread ID", description="The ID of the comment thread"
    )
    reply_id: str = Field(..., title="Reply ID", description="The ID of the reply")

    model_config = ConfigDict(title="Get Reply")


# ============================================================================
# OAuth Token Management Configs
# ============================================================================


class CanvaIntrospectTokenConfig(BaseModel):
    """Verify token validity and get token metadata"""

    operation: Literal["verify_token_validity"] = Field(
        "verify_token_validity",
        json_schema_extra={
            "const": "verify_token_validity",
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Verify Token Validity",
        },
        title="Verify Token Validity",
    )

    model_config = ConfigDict(title="Introspect Token")


class CanvaRevokeTokenConfig(BaseModel):
    """Revoke access or refresh token"""

    operation: Literal["revoke_access_or_refresh_token"] = Field(
        "revoke_access_or_refresh_token",
        json_schema_extra={
            "const": "revoke_access_or_refresh_token",
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Revoke Access or Refresh Token",
        },
        title="Revoke Access or Refresh Token",
    )
    token_type: Literal["access_token", "refresh_token"] = Field(
        "access_token", title="Token Type", description="Type of token to revoke"
    )

    model_config = ConfigDict(title="Revoke Token")


# ============================================================================
# Connect API Configs
# ============================================================================


class CanvaGetWebhookKeysConfig(BaseModel):
    """Get JSON Web Keys for webhook signature verification"""

    operation: Literal["get_webhook_signature_verification_keys"] = Field(
        "get_webhook_signature_verification_keys",
        json_schema_extra={
            "const": "get_webhook_signature_verification_keys",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook Signature Verification Keys",
        },
        title="Get Webhook Signature Verification Keys",
    )

    model_config = ConfigDict(title="Get Webhook Keys")


# ============================================================================
# OIDC Operation Configs
# ============================================================================


class CanvaGetOIDCJWKSConfig(BaseModel):
    """Get JSON Web Key Set for OpenID Connect"""

    operation: Literal["get_openid_connect_jwks"] = Field(
        "get_openid_connect_jwks",
        json_schema_extra={
            "const": "get_openid_connect_jwks",
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Get Openid Connect Jwks",
        },
        title="Get Openid Connect Jwks",
    )

    model_config = ConfigDict(title="Get OIDC JWKS")


class CanvaGetOIDCUserInfoConfig(BaseModel):
    """Fetch current user's OIDC claims"""

    operation: Literal["fetch_current_user_oidc_claims"] = Field(
        "fetch_current_user_oidc_claims",
        json_schema_extra={
            "const": "fetch_current_user_oidc_claims",
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Fetch Current User Oidc Claims",
        },
        title="Fetch Current User Oidc Claims",
    )

    model_config = ConfigDict(title="Get OIDC User Info")


# ============================================================================
# App JWT Configs
# ============================================================================


class CanvaGetAppJWKSConfig(BaseModel):
    """Get JSON Web Key Set of an app for JWT verification"""

    operation: Literal["get_app_json_web_key_set"] = Field(
        "get_app_json_web_key_set",
        json_schema_extra={
            "const": "get_app_json_web_key_set",
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Get App Json Web Key Set",
        },
        title="Get App Json Web Key Set",
    )
    app_id: str = Field(..., title="App ID", description="The ID of the app")

    model_config = ConfigDict(title="Get App JWKS")


# ============================================================================
# Discriminated Union
# ============================================================================

CanvaConfig = Annotated[
    Union[
        # Design operations (5)
        CanvaListDesignsConfig,
        CanvaCreateDesignConfig,
        CanvaGetDesignConfig,
        CanvaListDesignPagesConfig,
        CanvaGetExportFormatsConfig,
        # Asset operations (7 - includes binary upload)
        CanvaUploadAssetFromURLConfig,
        CanvaGetAssetConfig,
        CanvaUpdateAssetConfig,
        CanvaDeleteAssetConfig,
        CanvaGetAssetUploadJobConfig,
        CanvaCreateAssetUploadConfig,
        CanvaGetAssetUploadJobStatusConfig,
        # Export operations (2)
        CanvaCreateExportConfig,
        CanvaGetExportJobConfig,
        # Folder operations (6)
        CanvaCreateFolderConfig,
        CanvaGetFolderConfig,
        CanvaUpdateFolderConfig,
        CanvaDeleteFolderConfig,
        CanvaListFolderItemsConfig,
        CanvaMoveItemConfig,
        # User operations (3)
        CanvaGetUserConfig,
        CanvaGetUserProfileConfig,
        CanvaGetUserCapabilitiesConfig,
        # Resize operations (2 - GA)
        CanvaCreateResizeConfig,
        CanvaGetResizeJobConfig,
        # Design import operations (4 - URL + binary)
        CanvaImportFromURLConfig,
        CanvaGetImportJobConfig,
        CanvaCreateDesignImportConfig,
        CanvaGetDesignImportJobConfig,
        # Brand Template operations (3 - Preview)
        CanvaListBrandTemplatesConfig,
        CanvaGetBrandTemplateConfig,
        CanvaGetBrandTemplateDatasetConfig,
        # Autofill operations (2 - Preview)
        CanvaCreateAutofillJobConfig,
        CanvaGetAutofillJobConfig,
        # Comment operations (5 - Preview)
        CanvaCreateCommentThreadConfig,
        CanvaGetCommentThreadConfig,
        CanvaCreateReplyConfig,
        CanvaListRepliesConfig,
        CanvaGetReplyConfig,
        # OAuth Token Management (2)
        CanvaIntrospectTokenConfig,
        CanvaRevokeTokenConfig,
        # Connect API (1)
        CanvaGetWebhookKeysConfig,
        # OIDC operations (2)
        CanvaGetOIDCJWKSConfig,
        CanvaGetOIDCUserInfoConfig,
        # App JWT operations (1)
        CanvaGetAppJWKSConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class CanvaNodeConfig(NodeConfig[CanvaConfig, CanvaOAuthCredential]):
    """Full configuration for Canva node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class CanvaNode(WorkflowNode):
    """
    Canva Connect API automation node.

    Executes Canva API operations for workflow automation.
    Supports 50 operations across 13 categories:
    - Design Operations (5): list, create, get, list pages, get export formats
    - Asset Operations (7): upload from URL/binary, get, update, delete, get upload job status
    - Export Operations (2): create export, get export job
    - Folder Operations (6): create, get, update, delete, list items, move item
    - User Operations (3): get user, get profile, get capabilities
    - Resize Operations (2 - GA): create resize, get resize job
    - Design Import Operations (4): import from URL/binary, get import job status
    - Brand Template Operations (3 - Preview): list, get, get dataset
    - Autofill Operations (2 - Preview): create autofill, get autofill job
    - Comment Operations (5 - Preview): create thread, get thread, create reply, list replies, get reply
    - OAuth Token Management (2): introspect token, revoke token
    - Connect API (1): get webhook keys
    - OIDC Operations (2): get JWKS, get userinfo
    - App JWT Operations (1): get app JWKS
    """

    edit_examples = [
        'Create a new design in the "Marketing" folder with custom dimensions',
        "List all designs in the workspace and filter by status",
        "Export a design to PNG and download the file from the export URL",
        "Upload an image asset from a URL to the design library",
        "Create a resize job to generate thumbnails at 800x600 pixels",
        "Create an autofill job with template variables for a bulk design",
        "Get current user capabilities and check available tier features",
    ]

    scope_registry = CANVA_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_user_designs",
        noun="designs",
        identity_operation="get_user_profile_information",
    )
    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return CanvaNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, CanvaNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Canva account via OAuth."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Design operations
            "list_user_designs": self._handle_list_designs,
            "create_design": self._handle_create_design,
            "get_design_metadata": self._handle_get_design,
            "list_design_pages": self._handle_list_design_pages,
            "get_design_export_formats": self._handle_get_export_formats,
            # Asset operations
            "upload_asset_from_url": self._handle_upload_asset_from_url,
            "get_asset_metadata": self._handle_get_asset,
            "update_asset_name_or_tags": self._handle_update_asset,
            "delete_asset": self._handle_delete_asset,
            "get_asset_upload_job_status": self._handle_get_asset_upload_job,
            # Export operations
            "create_design_export_job": self._handle_create_export,
            "get_design_export_job_status": self._handle_get_export_job,
            # Folder operations
            "create_folder": self._handle_create_folder,
            "get_folder_details": self._handle_get_folder,
            "update_folder_name": self._handle_update_folder,
            "delete_folder": self._handle_delete_folder,
            "list_folder_contents": self._handle_list_folder_items,
            "move_item_to_folder": self._handle_move_item,
            # User operations
            "get_current_user_id": self._handle_get_user,
            "get_user_profile_information": self._handle_get_user_profile,
            "get_user_available_features": self._handle_get_user_capabilities,
            # Design import operations
            "import_design_from_url": self._handle_import_from_url,
            "get_design_import_job_status": self._handle_get_import_job,
            # Resize operations
            "create_design_resize_job": self._handle_create_resize,
            "get_design_resize_job_status": self._handle_get_resize_job,
            # Binary import operations
            "import_design_from_binary_file": self._handle_create_design_import,
            "get_binary_design_import_job_status": self._handle_get_design_import_job,
            # Binary asset upload operations
            "upload_asset_from_binary": self._handle_create_asset_upload,
            "get_binary_asset_upload_job_status": self._handle_get_asset_upload_job_status,
            # Brand template operations
            "list_brand_templates_with_search": self._handle_list_brand_templates,
            "get_brand_template_metadata": self._handle_get_brand_template,
            "get_autofill_dataset_definition": self._handle_get_brand_template_dataset,
            # Autofill operations
            "create_design_autofill_job": self._handle_create_autofill_job,
            "get_design_autofill_job_status": self._handle_get_autofill_job,
            # Comment operations
            "create_design_comment_thread": self._handle_create_comment_thread,
            "get_design_comment_thread": self._handle_get_comment_thread,
            "create_comment_thread_reply": self._handle_create_reply,
            "list_comment_thread_replies": self._handle_list_replies,
            "get_comment_thread_reply": self._handle_get_reply,
            # OAuth token management operations
            "verify_token_validity": self._handle_introspect_token,
            "revoke_access_or_refresh_token": self._handle_revoke_token,
            # Connect API operations
            "get_webhook_signature_verification_keys": self._handle_get_webhook_keys,
            # OIDC operations
            "get_openid_connect_jwks": self._handle_get_oidc_jwks,
            "fetch_current_user_oidc_claims": self._handle_get_oidc_userinfo,
            # App JWT operations
            "get_app_json_web_key_set": self._handle_get_app_jwks,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.canva_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="canva",
        )

    async def _get_access_token(self, credentials: CanvaOAuthCredential) -> str:
        """Return a valid Canva access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.canva_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="canva",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: CanvaOAuthCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Canva API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (without base URL, e.g., '/v1/designs')
            credentials: API credentials (OAuth)
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{CANVA_API_BASE}{endpoint}"

        # Get access token (handles refresh)
        access_token = await self._get_access_token(credentials)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get(
                            "message", error_data.get("error", str(error_data))
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[CanvaNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
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
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[CanvaNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Design Operation Handlers
    # =========================================================================

    async def _handle_list_designs(
        self, config: CanvaListDesignsConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """List user's designs."""
        params: Dict[str, Any] = {}
        if config.query:
            params["query"] = config.query
        if config.continuation:
            params["continuation"] = config.continuation
        if config.ownership:
            params["ownership"] = config.ownership

        return await self._make_request(
            method="GET",
            endpoint="/v1/designs",
            credentials=credentials,
            params=params if params else None,
            action_name="list_user_designs",
        )

    async def _handle_create_design(
        self, config: CanvaCreateDesignConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create a new design."""
        body: Dict[str, Any] = {
            "design_type": {"type": "preset", "name": config.design_type.lower()}
        }
        if config.title:
            body["title"] = config.title
        if config.asset_id:
            body["asset_id"] = config.asset_id

        return await self._make_request(
            method="POST",
            endpoint="/v1/designs",
            credentials=credentials,
            json_body=body,
            action_name="create_design",
        )

    async def _handle_get_design(
        self, config: CanvaGetDesignConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get design metadata."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}",
            credentials=credentials,
            action_name="get_design_metadata",
        )

    async def _handle_list_design_pages(
        self, config: CanvaListDesignPagesConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """List pages in a design."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}/pages",
            credentials=credentials,
            action_name="list_design_pages",
        )

    async def _handle_get_export_formats(
        self, config: CanvaGetExportFormatsConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get available export formats for a design."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}/export-formats",
            credentials=credentials,
            action_name="get_design_export_formats",
        )

    # =========================================================================
    # Asset Operation Handlers
    # =========================================================================

    async def _handle_upload_asset_from_url(
        self, config: CanvaUploadAssetFromURLConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Upload an asset from URL."""
        body: Dict[str, Any] = {"url": config.url}
        if config.name:
            body["name"] = config.name

        return await self._make_request(
            method="POST",
            endpoint="/v1/url-asset-uploads",
            credentials=credentials,
            json_body=body,
            action_name="upload_asset_from_url",
        )

    async def _handle_get_asset(
        self, config: CanvaGetAssetConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get asset metadata."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/assets/{config.asset_id}",
            credentials=credentials,
            action_name="get_asset_metadata",
        )

    async def _handle_update_asset(
        self, config: CanvaUpdateAssetConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Update asset name or tags."""
        body: Dict[str, Any] = {}
        if config.name is not None:
            body["name"] = config.name
        if config.tags is not None:
            body["tags"] = config.tags

        return await self._make_request(
            method="PATCH",
            endpoint=f"/v1/assets/{config.asset_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_asset_name_or_tags",
        )

    async def _handle_delete_asset(
        self, config: CanvaDeleteAssetConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Delete an asset."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/v1/assets/{config.asset_id}",
            credentials=credentials,
            action_name="delete_asset",
        )

    async def _handle_get_asset_upload_job(
        self, config: CanvaGetAssetUploadJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get asset upload job status."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/url-asset-uploads/{config.job_id}",
            credentials=credentials,
            action_name="get_binary_asset_upload_job_status",
        )

    # =========================================================================
    # Export Operation Handlers
    # =========================================================================

    async def _handle_create_export(
        self, config: CanvaCreateExportConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create a design export job."""
        # Build format object with type field
        format_obj: Dict[str, Any] = {"type": config.format}

        # Add format-specific options
        if config.pages:
            format_obj["pages"] = config.pages
        if config.quality:
            format_obj["export_quality"] = config.quality
        if config.lossless is not None and config.format == "png":
            format_obj["lossless"] = config.lossless

        body: Dict[str, Any] = {"design_id": config.design_id, "format": format_obj}

        return await self._make_request(
            method="POST",
            endpoint="/v1/exports",
            credentials=credentials,
            json_body=body,
            action_name="create_design_export_job",
        )

    async def _handle_get_export_job(
        self, config: CanvaGetExportJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get export job status."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/exports/{config.export_id}",
            credentials=credentials,
            action_name="get_design_export_job_status",
        )

    # =========================================================================
    # Folder Operation Handlers
    # =========================================================================

    async def _handle_create_folder(
        self, config: CanvaCreateFolderConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create a new folder."""
        body: Dict[str, Any] = {
            "name": config.name,
            "parent_folder_id": config.parent_folder_id or "root",
        }

        return await self._make_request(
            method="POST",
            endpoint="/v1/folders",
            credentials=credentials,
            json_body=body,
            action_name="create_folder",
        )

    async def _handle_get_folder(
        self, config: CanvaGetFolderConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get folder details."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/folders/{config.folder_id}",
            credentials=credentials,
            action_name="get_folder_details",
        )

    async def _handle_update_folder(
        self, config: CanvaUpdateFolderConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Update folder name."""
        body = {"name": config.name}

        return await self._make_request(
            method="PATCH",
            endpoint=f"/v1/folders/{config.folder_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_folder_name",
        )

    async def _handle_delete_folder(
        self, config: CanvaDeleteFolderConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Delete a folder."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/v1/folders/{config.folder_id}",
            credentials=credentials,
            action_name="delete_folder",
        )

    async def _handle_list_folder_items(
        self, config: CanvaListFolderItemsConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """List items in a folder."""
        params: Dict[str, Any] = {}
        if config.item_types:
            params["item_types"] = ",".join(config.item_types)
        if config.continuation:
            params["continuation"] = config.continuation

        return await self._make_request(
            method="GET",
            endpoint=f"/v1/folders/{config.folder_id}/items",
            credentials=credentials,
            params=params if params else None,
            action_name="list_folder_contents",
        )

    async def _handle_move_item(
        self, config: CanvaMoveItemConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Move an item to a folder."""
        body = {
            "item_id": config.item_id,
            "item_type": config.item_type,
            "to_folder_id": config.to_folder_id,
        }

        return await self._make_request(
            method="POST",
            endpoint="/v1/folders/move",
            credentials=credentials,
            json_body=body,
            action_name="move_item_to_folder",
        )

    # =========================================================================
    # User Operation Handlers
    # =========================================================================

    async def _handle_get_user(
        self, config: CanvaGetUserConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get current user ID."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/users/me",
            credentials=credentials,
            action_name="get_current_user_id",
        )

    async def _handle_get_user_profile(
        self, config: CanvaGetUserProfileConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get user profile information."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/users/me/profile",
            credentials=credentials,
            action_name="get_user_profile_information",
        )

    async def _handle_get_user_capabilities(
        self, config: CanvaGetUserCapabilitiesConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get user capabilities."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/users/me/capabilities",
            credentials=credentials,
            action_name="get_user_available_features",
        )

    # =========================================================================
    # Design Import Operation Handlers
    # =========================================================================

    async def _handle_import_from_url(
        self, config: CanvaImportFromURLConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Import a file as design from URL."""
        body: Dict[str, Any] = {"url": config.url}
        if config.title:
            body["title"] = config.title

        return await self._make_request(
            method="POST",
            endpoint="/v1/url-imports",
            credentials=credentials,
            json_body=body,
            action_name="import_design_from_url",
        )

    async def _handle_get_import_job(
        self, config: CanvaGetImportJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get import job status."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/url-imports/{config.job_id}",
            credentials=credentials,
            action_name="get_design_import_job_status",
        )

    # =========================================================================
    # Resize Operation Handlers
    # =========================================================================

    async def _handle_create_resize(
        self, config: CanvaCreateResizeConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create async job to resize a design to new dimensions."""
        body: Dict[str, Any] = {
            "design_id": config.design_id,
            "width": config.width,
            "height": config.height,
        }
        if config.title:
            body["title"] = config.title

        return await self._make_request(
            method="POST",
            endpoint="/v1/resizes",
            credentials=credentials,
            json_body=body,
            action_name="create_design_resize_job",
        )

    async def _handle_get_resize_job(
        self, config: CanvaGetResizeJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get status of a design resize job."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/resizes/{config.job_id}",
            credentials=credentials,
            action_name="get_design_resize_job_status",
        )

    # =========================================================================
    # Binary Design Import Operation Handlers
    # =========================================================================

    async def _handle_create_design_import(
        self, config: CanvaCreateDesignImportConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Import design from binary file data."""
        body: Dict[str, Any] = {"file_data": config.file_data}
        if config.title:
            body["title"] = config.title

        return await self._make_request(
            method="POST",
            endpoint="/v1/imports",
            credentials=credentials,
            json_body=body,
            action_name="import_design_from_binary_file",
        )

    async def _handle_get_design_import_job(
        self, config: CanvaGetDesignImportJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get status of binary design import job."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/imports/{config.job_id}",
            credentials=credentials,
            action_name="get_binary_design_import_job_status",
        )

    # =========================================================================
    # Binary Asset Upload Operation Handlers
    # =========================================================================

    async def _handle_create_asset_upload(
        self, config: CanvaCreateAssetUploadConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Upload asset from binary data."""
        body: Dict[str, Any] = {"file_data": config.file_data}
        if config.name:
            body["name"] = config.name
        if config.tags:
            body["tags"] = config.tags

        return await self._make_request(
            method="POST",
            endpoint="/v1/asset-uploads",
            credentials=credentials,
            json_body=body,
            action_name="upload_asset_from_binary",
        )

    async def _handle_get_asset_upload_job_status(
        self,
        config: CanvaGetAssetUploadJobStatusConfig,
        credentials: CanvaOAuthCredential,
    ) -> Dict[str, Any]:
        """Get status of binary asset upload job."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/asset-uploads/{config.job_id}",
            credentials=credentials,
            action_name="get_binary_asset_upload_job_status",
        )

    # =========================================================================
    # Brand Template Operation Handlers
    # =========================================================================

    async def _handle_list_brand_templates(
        self, config: CanvaListBrandTemplatesConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """List brand templates with search and filters."""
        params: Dict[str, Any] = {}
        if config.query:
            params["query"] = config.query
        if config.continuation:
            params["continuation"] = config.continuation

        return await self._make_request(
            method="GET",
            endpoint="/v1/brand-templates",
            credentials=credentials,
            params=params if params else None,
            action_name="list_brand_templates_with_search",
        )

    async def _handle_get_brand_template(
        self, config: CanvaGetBrandTemplateConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get brand template metadata."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/brand-templates/{config.brand_template_id}",
            credentials=credentials,
            action_name="get_brand_template_metadata",
        )

    async def _handle_get_brand_template_dataset(
        self,
        config: CanvaGetBrandTemplateDatasetConfig,
        credentials: CanvaOAuthCredential,
    ) -> Dict[str, Any]:
        """Get dataset definition for autofill fields."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/brand-templates/{config.brand_template_id}/dataset",
            credentials=credentials,
            action_name="get_autofill_dataset_definition",
        )

    # =========================================================================
    # Autofill Operation Handlers
    # =========================================================================

    async def _handle_create_autofill_job(
        self, config: CanvaCreateAutofillJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Start async job to autofill design using brand template."""
        body: Dict[str, Any] = {
            "brand_template_id": config.brand_template_id,
            "data": config.data,
        }
        if config.title:
            body["title"] = config.title

        return await self._make_request(
            method="POST",
            endpoint="/v1/autofills",
            credentials=credentials,
            json_body=body,
            action_name="create_design_autofill_job",
        )

    async def _handle_get_autofill_job(
        self, config: CanvaGetAutofillJobConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get status of design autofill job."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/autofills/{config.job_id}",
            credentials=credentials,
            action_name="get_design_autofill_job_status",
        )

    # =========================================================================
    # Comment Operation Handlers
    # =========================================================================

    async def _handle_create_comment_thread(
        self, config: CanvaCreateCommentThreadConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create comment thread on design."""
        body = {"message": config.message}

        return await self._make_request(
            method="POST",
            endpoint=f"/v1/designs/{config.design_id}/comments",
            credentials=credentials,
            json_body=body,
            action_name="create_design_comment_thread",
        )

    async def _handle_get_comment_thread(
        self, config: CanvaGetCommentThreadConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get comment or suggestion thread."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}/comments/{config.thread_id}",
            credentials=credentials,
            action_name="get_design_comment_thread",
        )

    async def _handle_create_reply(
        self, config: CanvaCreateReplyConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Create reply to comment thread."""
        body = {"message": config.message}

        return await self._make_request(
            method="POST",
            endpoint=f"/v1/designs/{config.design_id}/comments/{config.thread_id}/replies",
            credentials=credentials,
            json_body=body,
            action_name="create_comment_thread_reply",
        )

    async def _handle_list_replies(
        self, config: CanvaListRepliesConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """List replies for a comment thread."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}/comments/{config.thread_id}/replies",
            credentials=credentials,
            action_name="list_comment_thread_replies",
        )

    async def _handle_get_reply(
        self, config: CanvaGetReplyConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get specific reply from thread."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/designs/{config.design_id}/comments/{config.thread_id}/replies/{config.reply_id}",
            credentials=credentials,
            action_name="get_comment_thread_reply",
        )

    # =========================================================================
    # OAuth Token Management Operation Handlers
    # =========================================================================

    async def _handle_introspect_token(
        self, config: CanvaIntrospectTokenConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Verify token validity and get token metadata."""
        body = {"token": credentials.access_token}

        return await self._make_request(
            method="POST",
            endpoint="/v1/oauth/introspect",
            credentials=credentials,
            json_body=body,
            action_name="verify_token_validity",
        )

    async def _handle_revoke_token(
        self, config: CanvaRevokeTokenConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Revoke access or refresh token."""
        token = (
            credentials.access_token
            if config.token_type == "access_token"
            else credentials.refresh_token
        )
        body = {"token": token}

        return await self._make_request(
            method="POST",
            endpoint="/v1/oauth/revoke",
            credentials=credentials,
            json_body=body,
            action_name="revoke_access_or_refresh_token",
        )

    # =========================================================================
    # Connect API Operation Handlers
    # =========================================================================

    async def _handle_get_webhook_keys(
        self, config: CanvaGetWebhookKeysConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get JSON Web Keys for webhook signature verification."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/connect/keys",
            credentials=credentials,
            action_name="get_webhook_signature_verification_keys",
        )

    # =========================================================================
    # OIDC Operation Handlers
    # =========================================================================

    async def _handle_get_oidc_jwks(
        self, config: CanvaGetOIDCJWKSConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get JSON Web Key Set for OpenID Connect."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/oidc/jwks",
            credentials=credentials,
            action_name="get_openid_connect_jwks",
        )

    async def _handle_get_oidc_userinfo(
        self, config: CanvaGetOIDCUserInfoConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Fetch current user's OIDC claims."""
        return await self._make_request(
            method="GET",
            endpoint="/v1/oidc/userinfo",
            credentials=credentials,
            action_name="fetch_current_user_oidc_claims",
        )

    # =========================================================================
    # App JWT Operation Handlers
    # =========================================================================

    async def _handle_get_app_jwks(
        self, config: CanvaGetAppJWKSConfig, credentials: CanvaOAuthCredential
    ) -> Dict[str, Any]:
        """Get JSON Web Key Set of an app for JWT verification."""
        return await self._make_request(
            method="GET",
            endpoint=f"/v1/apps/{config.app_id}/jwks",
            credentials=credentials,
            action_name="get_app_json_web_key_set",
        )
