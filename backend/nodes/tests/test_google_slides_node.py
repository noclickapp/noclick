"""
Mock tests for Google Slides workflow node.

Tests Google Slides operations with mocked HTTP responses:
- Presentations: list_presentations, get_presentation, create_presentation
- Slides: get_page, add_slide, delete_slide

Uses httpx mocking to simulate Google Slides API responses without real credentials.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.google_slides_node import (
    GoogleSlidesNode,
    GoogleSlidesNodeConfig,
    GoogleSlidesOAuthCredential,
    # Presentation operations
    GoogleSlidesListPresentationsConfig,
    GoogleSlidesGetPresentationConfig,
    GoogleSlidesCreatePresentationConfig,
    # Slide operations
    GoogleSlidesGetPageConfig,
    GoogleSlidesAddSlideConfig,
    GoogleSlidesDeleteSlideConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

TEST_CREDENTIALS = GoogleSlidesOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",
    email="test@example.com",
)


def create_node(config) -> GoogleSlidesNode:
    """Create a GoogleSlidesNode instance with the given config."""
    node_config = GoogleSlidesNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return GoogleSlidesNode(
        node_id="test-node",
        node_type="automation-google-slides",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def mock_response(status_code: int, json_data: dict = None, text: str = ""):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text or ""
    response.json.return_value = json_data or {}
    return response


# ============================================================================
# Presentation Operations Tests
# ============================================================================


class TestListPresentations:
    """Test list_presentations operation."""

    @pytest.mark.asyncio
    async def test_list_presentations_success(self):
        """Test listing presentations returns presentations successfully."""
        config = GoogleSlidesListPresentationsConfig(page_size=50)
        node = create_node(config)

        mock_files = {
            "files": [
                {
                    "id": "pres123",
                    "name": "Q4 Report",
                    "mimeType": "application/vnd.google-apps.presentation",
                    "createdTime": "2024-01-10T10:00:00Z",
                    "modifiedTime": "2024-01-15T14:30:00Z",
                    "webViewLink": "https://docs.google.com/presentation/d/pres123/edit",
                },
                {
                    "id": "pres456",
                    "name": "Product Demo",
                    "mimeType": "application/vnd.google-apps.presentation",
                    "createdTime": "2024-01-12T09:00:00Z",
                    "modifiedTime": "2024-01-14T16:00:00Z",
                    "webViewLink": "https://docs.google.com/presentation/d/pres456/edit",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_google_drive_presentations"
            assert result["presentation_count"] == 2
            assert len(result["presentations"]) == 2

    @pytest.mark.asyncio
    async def test_list_presentations_empty(self):
        """Test listing presentations when none exist."""
        config = GoogleSlidesListPresentationsConfig()
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"files": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["presentation_count"] == 0
            assert result["presentations"] == []


class TestGetPresentation:
    """Test get_presentation operation."""

    @pytest.mark.asyncio
    async def test_get_presentation_success(self):
        """Test getting a single presentation."""
        config = GoogleSlidesGetPresentationConfig(presentation_id="pres123")
        node = create_node(config)

        mock_presentation = {
            "presentationId": "pres123",
            "title": "Q4 Report",
            "locale": "en_US",
            "revisionId": "revision123",
            "pageSize": {
                "width": {"magnitude": 9144000, "unit": "EMU"},
                "height": {"magnitude": 5143500, "unit": "EMU"},
            },
            "slides": [
                {"objectId": "slide1", "pageType": "SLIDE"},
                {"objectId": "slide2", "pageType": "SLIDE"},
            ],
            "masters": [{"objectId": "master1", "pageType": "MASTER"}],
            "layouts": [{"objectId": "layout1", "pageType": "LAYOUT"}],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_presentation)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_presentation_metadata"
            assert "presentation" in result
            assert result["presentation"]["presentationId"] == "pres123"
            assert result["presentation"]["slideCount"] == 2


class TestCreatePresentation:
    """Test create_presentation operation."""

    @pytest.mark.asyncio
    async def test_create_presentation_success(self):
        """Test creating a new presentation."""
        config = GoogleSlidesCreatePresentationConfig(title="New Presentation")
        node = create_node(config)

        mock_created = {
            "presentationId": "new_pres_id",
            "title": "New Presentation",
            "revisionId": "revision1",
            "slides": [{"objectId": "slide1", "pageType": "SLIDE"}],
            "pageSize": {
                "width": {"magnitude": 9144000, "unit": "EMU"},
                "height": {"magnitude": 5143500, "unit": "EMU"},
            },
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_presentation"
            assert result["presentation_id"] == "new_pres_id"


# ============================================================================
# Slide Operations Tests
# ============================================================================


class TestGetPage:
    """Test get_page operation."""

    @pytest.mark.asyncio
    async def test_get_page_success(self):
        """Test getting a single page/slide."""
        config = GoogleSlidesGetPageConfig(presentation_id="pres123", page_id="slide1")
        node = create_node(config)

        mock_page = {
            "objectId": "slide1",
            "pageType": "SLIDE",
            "pageProperties": {"colorScheme": {}},
            "slideProperties": {
                "layoutObjectId": "layout1",
                "masterObjectId": "master1",
            },
            "pageElements": [],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_page)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_slide_page"
            assert "page" in result
            assert result["page"]["objectId"] == "slide1"


class TestAddSlide:
    """Test add_slide operation."""

    @pytest.mark.asyncio
    async def test_add_slide_success(self):
        """Test adding a new slide to a presentation."""
        config = GoogleSlidesAddSlideConfig(
            presentation_id="pres123", insertion_index=1
        )
        node = create_node(config)

        mock_result = {
            "presentationId": "pres123",
            "replies": [{"createSlide": {"objectId": "new_slide_id"}}],
            "writeControl": {"requiredRevisionId": "revision2"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "add_presentation_slide"
            assert result["new_slide_id"] == "new_slide_id"

    @pytest.mark.asyncio
    async def test_add_slide_at_end(self):
        """Test adding a slide at the end."""
        config = GoogleSlidesAddSlideConfig(
            presentation_id="pres123"
            # No insertion_index means append at end
        )
        node = create_node(config)

        mock_result = {
            "presentationId": "pres123",
            "replies": [{"createSlide": {"objectId": "appended_slide"}}],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["new_slide_id"] == "appended_slide"


class TestDeleteSlide:
    """Test delete_slide operation."""

    @pytest.mark.asyncio
    async def test_delete_slide_success(self):
        """Test deleting a slide from a presentation."""
        config = GoogleSlidesDeleteSlideConfig(
            presentation_id="pres123", page_id="slide_to_delete"
        )
        node = create_node(config)

        mock_result = {
            "presentationId": "pres123",
            "replies": [{}],
            "writeControl": {"requiredRevisionId": "revision3"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_presentation_slide"
            assert result["deleted_page_id"] == "slide_to_delete"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_not_found(self):
        """Test handling of 404 errors."""
        config = GoogleSlidesGetPresentationConfig(presentation_id="nonexistent")
        node = create_node(config)

        error_response = {"error": {"code": 404, "message": "Presentation not found"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, error_response, "Presentation not found"
            )

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert (
                "404" in str(exc_info.value)
                or "not found" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_api_error_permission_denied(self):
        """Test handling of permission denied errors."""
        config = GoogleSlidesAddSlideConfig(presentation_id="protected_pres")
        node = create_node(config)

        error_response = {
            "error": {"code": 403, "message": "The caller does not have permission"}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(
                403, error_response, "Permission denied"
            )

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert (
                "403" in str(exc_info.value)
                or "permission" in str(exc_info.value).lower()
            )


# ============================================================================
# Dynamic Field Options Tests
# ============================================================================


class TestDynamicFieldOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_presentation_options(self):
        """Test loading presentation options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
            "email": "test@example.com",
        }

        mock_files = {
            "files": [
                {"id": "pres1", "name": "Presentation 1"},
                {"id": "pres2", "name": "Presentation 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await GoogleSlidesNode.load_field_options(
                "presentation_id", credential_data, None
            )

            # Dynamic options return a list
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["value"] == "pres1"
            assert result[0]["label"] == "Presentation 1"
