"""
Mock tests for Google Forms workflow node.

Tests Google Forms operations with mocked HTTP responses:
- Forms: list_forms, get_form, create_form, update_form
- Responses: list_responses, get_response

Uses httpx mocking to simulate Google Forms API responses without real credentials.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.google_forms_node import (
    GoogleFormsNode,
    GoogleFormsNodeConfig,
    GoogleFormsOAuthCredential,
    # Form operations
    GoogleFormsListFormsConfig,
    GoogleFormsGetFormConfig,
    GoogleFormsCreateFormConfig,
    GoogleFormsUpdateFormConfig,
    # Response operations
    GoogleFormsListResponsesConfig,
    GoogleFormsGetResponseConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

TEST_CREDENTIALS = GoogleFormsOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",
    email="test@example.com",
)


def create_node(config) -> GoogleFormsNode:
    """Create a GoogleFormsNode instance with the given config."""
    node_config = GoogleFormsNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return GoogleFormsNode(
        node_id="test-node",
        node_type="automation-google-forms",
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
# Form Operations Tests
# ============================================================================


class TestListForms:
    """Test list_forms operation."""

    @pytest.mark.asyncio
    async def test_list_forms_success(self):
        """Test listing forms returns forms successfully."""
        config = GoogleFormsListFormsConfig(page_size=50)
        node = create_node(config)

        mock_files = {
            "files": [
                {
                    "id": "form123",
                    "name": "Customer Feedback",
                    "mimeType": "application/vnd.google-apps.form",
                    "createdTime": "2024-01-10T10:00:00Z",
                    "modifiedTime": "2024-01-15T14:30:00Z",
                    "webViewLink": "https://docs.google.com/forms/d/form123/edit",
                },
                {
                    "id": "form456",
                    "name": "Event Registration",
                    "mimeType": "application/vnd.google-apps.form",
                    "createdTime": "2024-01-12T09:00:00Z",
                    "modifiedTime": "2024-01-14T16:00:00Z",
                    "webViewLink": "https://docs.google.com/forms/d/form456/edit",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_google_drive_forms"
            assert result["form_count"] == 2
            assert len(result["forms"]) == 2

    @pytest.mark.asyncio
    async def test_list_forms_empty(self):
        """Test listing forms when none exist."""
        config = GoogleFormsListFormsConfig()
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"files": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["form_count"] == 0
            assert result["forms"] == []


class TestGetForm:
    """Test get_form operation."""

    @pytest.mark.asyncio
    async def test_get_form_success(self):
        """Test getting a single form."""
        config = GoogleFormsGetFormConfig(form_id="form123")
        node = create_node(config)

        mock_form = {
            "formId": "form123",
            "info": {
                "title": "Customer Feedback Survey",
                "documentTitle": "Customer Feedback Survey",
            },
            "items": [{"itemId": "item1", "title": "How satisfied are you?"}],
            "responderUri": "https://docs.google.com/forms/d/form123/viewform",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_form)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_form_metadata"
            assert "form" in result
            assert result["form"]["formId"] == "form123"


class TestCreateForm:
    """Test create_form operation."""

    @pytest.mark.asyncio
    async def test_create_form_success(self):
        """Test creating a new form."""
        config = GoogleFormsCreateFormConfig(
            title="New Survey", description="Please fill out this survey."
        )
        node = create_node(config)

        mock_created = {
            "formId": "new_form_id",
            "info": {
                "title": "New Survey",
                "description": "Please fill out this survey.",
            },
            "responderUri": "https://docs.google.com/forms/d/new_form_id/viewform",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_form"
            assert result["form_id"] == "new_form_id"

    @pytest.mark.asyncio
    async def test_create_form_minimal(self):
        """Test creating a form with just a title."""
        config = GoogleFormsCreateFormConfig(title="Simple Form")
        node = create_node(config)

        mock_created = {
            "formId": "simple_form_id",
            "info": {"title": "Simple Form"},
            "responderUri": "https://docs.google.com/forms/d/simple_form_id/viewform",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"


class TestUpdateForm:
    """Test update_form operation."""

    @pytest.mark.asyncio
    async def test_update_form_success(self):
        """Test updating an existing form."""
        config = GoogleFormsUpdateFormConfig(
            form_id="form123",
            title="Updated Survey Title",
            description="Updated description",
        )
        node = create_node(config)

        mock_result = {
            "replies": [{}],
            "writeControl": {"requiredRevisionId": "revision2"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_form_metadata"


# ============================================================================
# Response Operations Tests
# ============================================================================


class TestListResponses:
    """Test list_responses operation."""

    @pytest.mark.asyncio
    async def test_list_responses_success(self):
        """Test listing form responses."""
        config = GoogleFormsListResponsesConfig(form_id="form123")
        node = create_node(config)

        mock_responses = {
            "responses": [
                {
                    "responseId": "resp1",
                    "createTime": "2024-01-15T10:00:00Z",
                    "lastSubmittedTime": "2024-01-15T10:05:00Z",
                    "answers": {"q1": {"textAnswers": {"answers": [{"value": "5"}]}}},
                },
                {
                    "responseId": "resp2",
                    "createTime": "2024-01-15T11:00:00Z",
                    "lastSubmittedTime": "2024-01-15T11:03:00Z",
                    "answers": {"q1": {"textAnswers": {"answers": [{"value": "4"}]}}},
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_responses)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_form_responses"
            assert result["response_count"] == 2
            assert len(result["responses"]) == 2

    @pytest.mark.asyncio
    async def test_list_responses_empty(self):
        """Test listing responses when none exist."""
        config = GoogleFormsListResponsesConfig(form_id="form123")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"responses": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["response_count"] == 0
            assert result["responses"] == []


class TestGetResponse:
    """Test get_response operation."""

    @pytest.mark.asyncio
    async def test_get_response_success(self):
        """Test getting a single form response."""
        config = GoogleFormsGetResponseConfig(form_id="form123", response_id="resp1")
        node = create_node(config)

        mock_response_data = {
            "responseId": "resp1",
            "createTime": "2024-01-15T10:00:00Z",
            "lastSubmittedTime": "2024-01-15T10:05:00Z",
            "respondentEmail": "user@example.com",
            "answers": {
                "q1": {"questionId": "q1", "textAnswers": {"answers": [{"value": "5"}]}}
            },
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_response_data)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_form_response"
            assert "response" in result


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_not_found(self):
        """Test handling of 404 errors."""
        config = GoogleFormsGetFormConfig(form_id="nonexistent")
        node = create_node(config)

        error_response = {"error": {"code": 404, "message": "Form not found"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, error_response, "Form not found"
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
        config = GoogleFormsListResponsesConfig(form_id="protected_form")
        node = create_node(config)

        error_response = {
            "error": {"code": 403, "message": "The caller does not have permission"}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
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
    async def test_load_form_options(self):
        """Test loading form options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
            "email": "test@example.com",
        }

        mock_files = {
            "files": [
                {"id": "form1", "name": "Survey 1"},
                {"id": "form2", "name": "Survey 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await GoogleFormsNode.load_field_options(
                "form_id", credential_data, None
            )

            # Dynamic options return a list
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["value"] == "form1"
            assert result[0]["label"] == "Survey 1"
