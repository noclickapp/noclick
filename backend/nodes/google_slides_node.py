"""
Google Slides workflow node implementation.
Enables creating and modifying Google Slides presentations via OAuth credentials.

Supports 6 operations:
- Presentations: list_presentations, get_presentation, create_presentation
- Slides: get_page, add_slide, delete_slide
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google import GOOGLE_SLIDES_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_SLIDES_API_BASE = "https://slides.googleapis.com/v1/presentations"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


# ============================================================================
# Google Slides Node Credential Schema
# ============================================================================


class GoogleSlidesOAuthCredential(BaseModel):
    """
    OAuth credential for Google Slides access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_slides_oauth"] = Field(
        "google_slides_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
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
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": [
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/drive",
        ],
    })


# ============================================================================
# Google Slides Node Configuration Models
# ============================================================================


class GoogleSlidesListPresentationsConfig(BaseModel):
    """Configuration for listing presentations from Google Drive"""

    operation: Literal["list_google_drive_presentations"] = Field(
        "list_google_drive_presentations",
        title="List Google Drive Presentations",
        description="List Google Slides presentations",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_google_drive_presentations",
            "x-category": "Presentation",
            "x-is-trigger": False,
            "x-display-name": "List Google Drive Presentations",
        },
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Maximum number of presentations to return (1-100)",
        ge=1,
        le=100,
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search term to filter presentations by name",
        json_schema_extra={"placeholder": "Presentation name (optional)"},
    )


class GoogleSlidesGetPresentationConfig(BaseModel):
    """Configuration for getting a presentation"""

    operation: Literal["get_presentation_metadata"] = Field(
        "get_presentation_metadata",
        title="Get Presentation Metadata",
        description="Get a presentation",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_presentation_metadata",
            "x-category": "Presentation",
            "x-is-trigger": False,
            "x-display-name": "Get Presentation Metadata",
        },
    )
    presentation_id: str = Field(
        ...,
        title="Presentation",
        description="Select a Google Slides presentation",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "presentation_id",
                "placeholder": "Select a presentation...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste presentation ID",
            },
            "x-resource-type": "google_presentation",
        },
    )


class GoogleSlidesCreatePresentationConfig(BaseModel):
    """Configuration for creating a new presentation"""

    operation: Literal["create_new_presentation"] = Field(
        "create_new_presentation",
        title="Create New Presentation",
        description="Create a new presentation",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_presentation",
            "x-category": "Presentation",
            "x-is-trigger": False,
            "x-display-name": "Create New Presentation",
            "x-creates-resource": True,
            "x-resource-type": "google_presentation",
            "x-resource-id-path": "presentation.presentationId",
        },
    )
    title: str = Field(
        ...,
        title="Title",
        description="Title for the new presentation",
        json_schema_extra={"placeholder": "My Presentation"},
    )


class GoogleSlidesGetPageConfig(BaseModel):
    """Configuration for getting a specific slide/page"""

    operation: Literal["get_slide_page"] = Field(
        "get_slide_page",
        title="Get Slide Page",
        description="Get a specific slide",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_slide_page",
            "x-category": "Slide",
            "x-is-trigger": False,
            "x-display-name": "Get Slide Page",
        },
    )
    presentation_id: str = Field(
        ...,
        title="Presentation",
        description="Select a Google Slides presentation",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "presentation_id",
                "placeholder": "Select a presentation...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste presentation ID",
            },
            "x-resource-type": "google_presentation",
        },
    )
    page_id: str = Field(
        ...,
        title="Page ID",
        description="The ID of the slide/page to retrieve",
        json_schema_extra={"placeholder": "Slide ID"},
    )


class GoogleSlidesAddSlideConfig(BaseModel):
    """Configuration for adding a new slide"""

    operation: Literal["add_presentation_slide"] = Field(
        "add_presentation_slide",
        title="Add Presentation Slide",
        description="Add a new slide",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_presentation_slide",
            "x-category": "Slide",
            "x-is-trigger": False,
            "x-display-name": "Add Presentation Slide",
        },
    )
    presentation_id: str = Field(
        ...,
        title="Presentation",
        description="Select a Google Slides presentation",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "presentation_id",
                "placeholder": "Select a presentation...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste presentation ID",
            },
            "x-resource-type": "google_presentation",
        },
    )
    layout: Optional[
        Literal[
            "BLANK",
            "TITLE",
            "TITLE_AND_BODY",
            "TITLE_AND_TWO_COLUMNS",
            "TITLE_ONLY",
            "ONE_COLUMN_TEXT",
            "MAIN_POINT",
            "BIG_NUMBER",
        ]
    ] = Field(
        "BLANK", title="Layout", description="Predefined layout for the new slide"
    )
    insertion_index: Optional[int] = Field(
        None,
        title="Position",
        description="Position to insert the slide (0 = first). Leave empty for end.",
        ge=0,
    )


class GoogleSlidesDeleteSlideConfig(BaseModel):
    """Configuration for deleting a slide"""

    operation: Literal["delete_presentation_slide"] = Field(
        "delete_presentation_slide",
        title="Delete Presentation Slide",
        description="Delete a slide",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_presentation_slide",
            "x-category": "Slide",
            "x-is-trigger": False,
            "x-display-name": "Delete Presentation Slide",
        },
    )
    presentation_id: str = Field(
        ...,
        title="Presentation",
        description="Select a Google Slides presentation",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "presentation_id",
                "placeholder": "Select a presentation...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste presentation ID",
            },
            "x-resource-type": "google_presentation",
        },
    )
    page_id: str = Field(
        ...,
        title="Page ID",
        description="The ID of the slide to delete",
        json_schema_extra={"placeholder": "Slide ID"},
    )


class GoogleSlidesGetThumbnailConfig(BaseModel):
    """Configuration for getting a slide thumbnail"""

    operation: Literal["get_slide_thumbnail"] = Field(
        "get_slide_thumbnail",
        title="Get Slide Thumbnail",
        description="Get a slide thumbnail image",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_slide_thumbnail",
            "x-category": "Slide",
            "x-is-trigger": False,
            "x-display-name": "Get Slide Thumbnail",
        },
    )
    presentation_id: str = Field(
        ...,
        title="Presentation",
        description="Select a Google Slides presentation",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "presentation_id",
                "placeholder": "Select a presentation...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste presentation ID",
            },
            "x-resource-type": "google_presentation",
        },
    )
    page_id: str = Field(
        ...,
        title="Page ID",
        description="The ID of the slide to get thumbnail for",
        json_schema_extra={"placeholder": "Slide ID"},
    )
    thumbnail_size: Optional[Literal["SMALL", "MEDIUM", "LARGE"]] = Field(
        "MEDIUM", title="Thumbnail Size", description="Size of the thumbnail image"
    )


# Union of all config types for oneOf schema
GoogleSlidesConfig = Annotated[
    Union[
        GoogleSlidesListPresentationsConfig,
        GoogleSlidesGetPresentationConfig,
        GoogleSlidesCreatePresentationConfig,
        GoogleSlidesGetPageConfig,
        GoogleSlidesAddSlideConfig,
        GoogleSlidesDeleteSlideConfig,
        GoogleSlidesGetThumbnailConfig,
    ],
    Discriminator("operation"),
]


class GoogleSlidesNodeConfig(
    NodeConfig[GoogleSlidesConfig, GoogleSlidesOAuthCredential]
):
    """Full configuration for Google Slides node including credentials"""

    pass


# ============================================================================
# Google Slides Node Implementation
# ============================================================================


class GoogleSlidesNode(WorkflowNode):
    """
    Google Slides workflow node for managing presentations.
    """

    edit_examples = [
        "Create a new Q2 earnings presentation and add title slide",
        "Add 5 new slides to the product roadmap deck with bullet points",
        "Get all slides from the sales pitch and extract content for PDF",
        "Delete old slides from 2024 and reorganize remaining content",
        "List all presentations in the Campaigns folder and count total slides",
        "Get thumbnail of the first slide from investor deck for preview",
        "Move the latest template to shared folder and add team members",
    ]

    scope_registry = GOOGLE_SLIDES_SCOPES
    connection_evidence = ConnectionEvidence(
        field="presentation_id",
        noun="presentations",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Slides node"""
        return GoogleSlidesNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load dynamic options for a field."""
        logger.info(f"[GoogleSlidesNode] load_field_options called: field={field_name}")
        if field_name == "presentation_id":
            return await cls._list_presentations_options(credential_data, search=search)
        return []

    @classmethod
    async def _list_presentations_options(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List Google Slides for dropdown options."""
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load presentations",
        )

        # Query Drive API for Google Slides files
        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        query_parts = [
            "mimeType='application/vnd.google-apps.presentation'",
            "trashed=false",
        ]
        if search:
            escaped_search = search.replace("'", "\\'")
            query_parts.append(f"name contains '{escaped_search}'")
        params = {
            "q": " and ".join(query_parts),
            "fields": "files(id,name,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    logger.error(f"[GoogleSlidesNode] Drive API error: {error_msg}")
                    raise ValueError(f"Google Drive API error: {error_msg}")

                data = response.json()
                files = data.get("files", [])

                options = []
                for f in files:
                    options.append(
                        {
                            "value": f.get("id"),
                            "label": f.get("name", f.get("id")),
                            "metadata": {"modifiedTime": f.get("modifiedTime")},
                        }
                    )

                logger.info(f"[GoogleSlidesNode] Found {len(options)} presentations")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GoogleSlidesNode] Error listing presentations: {e}")
            raise ValueError(f"Failed to load Google Slides options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Slides operation."""
        logger.info(f"[GoogleSlidesNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleSlidesNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleSlidesNodeConfig):
            raise ValueError(
                f"[GoogleSlidesNode] Invalid config type: {type(node_config)}, expected GoogleSlidesNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                f"[GoogleSlidesNode] Google Slides credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleSlidesListPresentationsConfig):
            output = await self._list_presentations(config, access_token)
        elif isinstance(config, GoogleSlidesGetPresentationConfig):
            output = await self._get_presentation(config, access_token)
        elif isinstance(config, GoogleSlidesCreatePresentationConfig):
            output = await self._create_presentation(config, access_token)
        elif isinstance(config, GoogleSlidesGetPageConfig):
            output = await self._get_page(config, access_token)
        elif isinstance(config, GoogleSlidesAddSlideConfig):
            output = await self._add_slide(config, access_token)
        elif isinstance(config, GoogleSlidesDeleteSlideConfig):
            output = await self._delete_slide(config, access_token)
        elif isinstance(config, GoogleSlidesGetThumbnailConfig):
            output = await self._get_thumbnail(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(
        self, credentials: GoogleSlidesOAuthCredential
    ) -> str:
        """Return a valid Google Slides access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _list_presentations(
        self, config: GoogleSlidesListPresentationsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List Google Slides presentations from Drive."""
        logger.info(f"[GoogleSlidesNode] Listing presentations")

        url = f"{GOOGLE_DRIVE_API_BASE}/files"

        # Build query for Google Slides
        query_parts = [
            "mimeType='application/vnd.google-apps.presentation'",
            "trashed=false",
        ]
        if config.search_query:
            query_parts.append(f"name contains '{config.search_query}'")

        params: Dict[str, Any] = {
            "q": " and ".join(query_parts),
            "fields": "files(id,name,modifiedTime,createdTime,owners)",
            "orderBy": "modifiedTime desc",
        }

        if config.page_size:
            params["pageSize"] = config.page_size

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleSlidesNode] List presentations failed: {error_msg}"
                )
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            files = data.get("files", [])

            presentations = []
            for f in files:
                presentations.append(
                    {
                        "id": f.get("id"),
                        "name": f.get("name"),
                        "modifiedTime": f.get("modifiedTime"),
                        "createdTime": f.get("createdTime"),
                        "owners": f.get("owners", []),
                    }
                )

            output = {
                "type": "google_slides",
                "operation": "list_google_drive_presentations",
                "presentation_count": len(presentations),
                "presentations": presentations,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleSlidesNode] Listed {len(presentations)} presentations")
            return output

    async def _get_presentation(
        self, config: GoogleSlidesGetPresentationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a presentation."""
        logger.info(f"[GoogleSlidesNode] Getting presentation {config.presentation_id}")

        url = f"{GOOGLE_SLIDES_API_BASE}/{config.presentation_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSlidesNode] Get presentation failed: {error_msg}")
                raise ValueError(f"Google Slides API error: {error_msg}")

            pres = response.json()

            # Simplify slides
            slides = []
            for slide in pres.get("slides", []):
                slides.append(
                    {
                        "objectId": slide.get("objectId"),
                        "pageType": slide.get("pageType"),
                        "slideProperties": slide.get("slideProperties", {}),
                    }
                )

            output = {
                "type": "google_slides",
                "operation": "get_presentation_metadata",
                "presentation": {
                    "presentationId": pres.get("presentationId"),
                    "title": pres.get("title"),
                    "pageSize": pres.get("pageSize"),
                    "slideCount": len(slides),
                    "slides": slides,
                    "masters": [m.get("objectId") for m in pres.get("masters", [])],
                    "layouts": [l.get("objectId") for l in pres.get("layouts", [])],
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleSlidesNode] Retrieved presentation: {pres.get('title')}"
            )
            return output

    async def _create_presentation(
        self, config: GoogleSlidesCreatePresentationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new presentation."""
        logger.info(f"[GoogleSlidesNode] Creating presentation: {config.title}")

        url = GOOGLE_SLIDES_API_BASE

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"title": config.title},
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleSlidesNode] Create presentation failed: {error_msg}"
                )
                raise ValueError(f"Google Slides API error: {error_msg}")

            pres = response.json()

            output = {
                "type": "google_slides",
                "operation": "create_new_presentation",
                "presentation_id": pres.get("presentationId"),
                "presentation": {
                    "presentationId": pres.get("presentationId"),
                    "title": pres.get("title"),
                    "slideCount": len(pres.get("slides", [])),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleSlidesNode] Created presentation: {pres.get('presentationId')}"
            )
            return output

    async def _get_page(
        self, config: GoogleSlidesGetPageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific slide/page."""
        logger.info(f"[GoogleSlidesNode] Getting page {config.page_id}")

        url = (
            f"{GOOGLE_SLIDES_API_BASE}/{config.presentation_id}/pages/{config.page_id}"
        )

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSlidesNode] Get page failed: {error_msg}")
                raise ValueError(f"Google Slides API error: {error_msg}")

            page = response.json()

            output = {
                "type": "google_slides",
                "operation": "get_slide_page",
                "presentation_id": config.presentation_id,
                "page": {
                    "objectId": page.get("objectId"),
                    "pageType": page.get("pageType"),
                    "slideProperties": page.get("slideProperties", {}),
                    "pageProperties": page.get("pageProperties", {}),
                    "pageElements": page.get("pageElements", []),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleSlidesNode] Retrieved page: {config.page_id}")
            return output

    async def _add_slide(
        self, config: GoogleSlidesAddSlideConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a new slide to the presentation."""
        logger.info(
            f"[GoogleSlidesNode] Adding slide to presentation {config.presentation_id}"
        )

        url = f"{GOOGLE_SLIDES_API_BASE}/{config.presentation_id}:batchUpdate"

        # Build the create slide request
        create_slide_request: Dict[str, Any] = {"createSlide": {}}

        if config.insertion_index is not None:
            create_slide_request["createSlide"][
                "insertionIndex"
            ] = config.insertion_index

        if config.layout and config.layout != "BLANK":
            create_slide_request["createSlide"]["slideLayoutReference"] = {
                "predefinedLayout": config.layout
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [create_slide_request]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSlidesNode] Add slide failed: {error_msg}")
                raise ValueError(f"Google Slides API error: {error_msg}")

            result = response.json()
            replies = result.get("replies", [])
            new_slide_id = None
            if replies and "createSlide" in replies[0]:
                new_slide_id = replies[0]["createSlide"].get("objectId")

            output = {
                "type": "google_slides",
                "operation": "add_presentation_slide",
                "presentation_id": config.presentation_id,
                "new_slide_id": new_slide_id,
                "layout": config.layout,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleSlidesNode] Added slide: {new_slide_id}")
            return output

    async def _delete_slide(
        self, config: GoogleSlidesDeleteSlideConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a slide from the presentation."""
        logger.info(f"[GoogleSlidesNode] Deleting slide {config.page_id}")

        url = f"{GOOGLE_SLIDES_API_BASE}/{config.presentation_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [{"deleteObject": {"objectId": config.page_id}}]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSlidesNode] Delete slide failed: {error_msg}")
                raise ValueError(f"Google Slides API error: {error_msg}")

            output = {
                "type": "google_slides",
                "operation": "delete_presentation_slide",
                "presentation_id": config.presentation_id,
                "deleted_page_id": config.page_id,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleSlidesNode] Deleted slide: {config.page_id}")
            return output

    async def _get_thumbnail(
        self, config: GoogleSlidesGetThumbnailConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a thumbnail image for a slide."""
        logger.info(f"[GoogleSlidesNode] Getting thumbnail for slide {config.page_id}")

        # Map size to API parameter
        size_map = {"SMALL": "SMALL", "MEDIUM": "MEDIUM", "LARGE": "LARGE"}
        thumbnail_size = size_map.get(config.thumbnail_size or "MEDIUM", "MEDIUM")

        url = f"{GOOGLE_SLIDES_API_BASE}/{config.presentation_id}/pages/{config.page_id}/thumbnail"
        params = {
            "thumbnailProperties.thumbnailSize": thumbnail_size,
            "thumbnailProperties.mimeType": "PNG",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSlidesNode] Get thumbnail failed: {error_msg}")
                raise ValueError(f"Google Slides API error: {error_msg}")

            data = response.json()

            output = {
                "type": "google_slides",
                "operation": "get_slide_thumbnail",
                "presentation_id": config.presentation_id,
                "page_id": config.page_id,
                "thumbnail": {
                    "contentUrl": data.get("contentUrl"),
                    "width": data.get("width"),
                    "height": data.get("height"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleSlidesNode] Retrieved thumbnail for slide: {config.page_id}"
            )
            return output
