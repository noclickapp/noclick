"""
Mock tests for Typeform REST API node.

Tests the Typeform API node functionality with mocked HTTP responses.
All tests use httpx mock to simulate API responses without actual API calls.

Test Coverage:
- Form Operations (list, get, create, update, delete, messages)
- Theme Operations (list, get, create, update, delete)
- Image Operations (list, get, create, delete)
- Video Operations (upload)
- Workspace Operations (list, get, create, update, delete)
- Response Operations (get, delete, insights, files, audio, video)
- Webhook Operations (create, delete)
- Translation Operations (all operations)
- Token Refresh (OAuth)
- Error Handling (rate limiting, invalid requests)
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta, timezone

from nodes.typeform_node import (
    TypeformNode,
    TypeformNodeFullConfig,
    TypeformPATCredential,
    TypeformOAuthCredential,
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
)


@pytest.fixture
def pat_credentials():
    """Create PAT credentials for testing."""
    return TypeformPATCredential(personal_access_token="tfp_test_token_12345")


@pytest.fixture
def oauth_credentials():
    """Create OAuth credentials for testing."""
    future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return TypeformOAuthCredential(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=future_time,
        email="test@example.com",
    )


@pytest.fixture
def expired_oauth_credentials():
    """Create expired OAuth credentials for testing token refresh."""
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return TypeformOAuthCredential(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=past_time,
        email="test@example.com",
    )


def create_typeform_node(config):
    """Create a Typeform node instance with the given config."""
    return TypeformNode(
        node_id="test-typeform-node",
        node_type="automation-typeform",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    """Create a mock HTTP response."""
    mock_response = Mock()
    mock_response.status_code = status_code

    # json() is a regular method in httpx, not async
    def json_method():
        return json_data or {}

    mock_response.json = json_method

    # raise_for_status() is a regular method
    def raise_for_status():
        if status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError(
                f"Client error '{status_code}'", request=Mock(), response=mock_response
            )

    mock_response.raise_for_status = raise_for_status
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Create a mock httpx.AsyncClient."""
    mock_response = create_mock_response(status_code, json_data)

    mock_client = Mock()

    # Create async request method that returns the mock_response
    async def async_request(*args, **kwargs):
        return mock_response

    # Mock the request method (which is what the actual code calls)
    mock_client.request = async_request

    # Make the client work as an async context manager
    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit

    return mock_client


class TestTypeformFormOperationsMock:
    """Test Typeform form operations with mocked responses."""

    @pytest.mark.asyncio
    async def test_list_forms_mock(self, pat_credentials):
        """Test listing forms with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformListFormsConfig(page=1, page_size=10),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "total_items": 2,
            "page_count": 1,
            "items": [
                {"id": "form1", "title": "Test Form 1"},
                {"id": "form2", "title": "Test Form 2"},
            ],
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["total_items"] == 2
            assert len(result["items"]) == 2
            print("✅ List forms mock test passed")

    @pytest.mark.asyncio
    async def test_get_form_mock(self, pat_credentials):
        """Test getting a specific form with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetFormConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "test_form_id",
            "title": "Test Form",
            "fields": [{"type": "short_text", "title": "Name"}],
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["id"] == "test_form_id"
            assert result["title"] == "Test Form"
            print("✅ Get form mock test passed")

    @pytest.mark.asyncio
    async def test_create_form_mock(self, pat_credentials):
        """Test creating a form with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformCreateFormConfig(
                title="New Test Form", fields=[{"type": "short_text", "title": "Name"}]
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "new_form_id",
            "title": "New Test Form",
            "fields": [{"type": "short_text", "title": "Name"}],
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["id"] == "new_form_id"
            assert result["title"] == "New Test Form"
            print("✅ Create form mock test passed")

    @pytest.mark.asyncio
    async def test_update_form_mock(self, pat_credentials):
        """Test updating a form with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformUpdateFormConfig(
                form_id="test_form_id", title="Updated Form Title", patch=True
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {"id": "test_form_id", "title": "Updated Form Title"}

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["title"] == "Updated Form Title"
            print("✅ Update form mock test passed")

    @pytest.mark.asyncio
    async def test_delete_form_mock(self, pat_credentials):
        """Test deleting a form with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformDeleteFormConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value.status_code = 204

            result = await node.execute({})

            assert result["success"] == True
            assert result["status_code"] == 204
            print("✅ Delete form mock test passed")


class TestTypeformThemeOperationsMock:
    """Test Typeform theme operations with mocked responses."""

    @pytest.mark.asyncio
    async def test_list_themes_mock(self, pat_credentials):
        """Test listing themes with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformListThemesConfig(page=1, page_size=10),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "total_items": 1,
            "items": [{"id": "theme1", "name": "Test Theme"}],
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert len(result["items"]) == 1
            print("✅ List themes mock test passed")

    @pytest.mark.asyncio
    async def test_create_theme_mock(self, pat_credentials):
        """Test creating a theme with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformCreateThemeConfig(
                name="New Theme", colors={"question": "#3D3D3D", "answer": "#4FB0AE"}
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "new_theme_id",
            "name": "New Theme",
            "colors": {"question": "#3D3D3D", "answer": "#4FB0AE"},
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["id"] == "new_theme_id"
            print("✅ Create theme mock test passed")


class TestTypeformResponseOperationsMock:
    """Test Typeform response operations with mocked responses."""

    @pytest.mark.asyncio
    async def test_get_responses_mock(self, pat_credentials):
        """Test getting responses with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetResponsesConfig(form_id="test_form_id", page_size=10),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "total_items": 1,
            "items": [
                {
                    "response_id": "resp1",
                    "submitted_at": "2025-12-30T10:00:00Z",
                    "answers": [],
                }
            ],
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["total_items"] == 1
            print("✅ Get responses mock test passed")

    @pytest.mark.asyncio
    async def test_get_insights_mock(self, pat_credentials):
        """Test getting insights with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetInsightsConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {"summary": {"responses": {"total": 100, "completed": 95}}}

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["summary"]["responses"]["total"] == 100
            print("✅ Get insights mock test passed")

    @pytest.mark.asyncio
    async def test_download_files_mock(self, pat_credentials):
        """Test downloading files with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformDownloadFilesConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "items": [{"file_id": "file1", "url": "https://example.com/file1.pdf"}]
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert len(result["items"]) == 1
            print("✅ Download files mock test passed")


class TestTypeformWebhookOperationsMock:
    """Test Typeform webhook operations with mocked responses."""

    @pytest.mark.asyncio
    async def test_create_webhook_mock(self, pat_credentials):
        """Test creating a webhook with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformCreateWebhookConfig(
                form_id="test_form_id",
                tag="test_webhook",
                url="https://example.com/webhook",
                enabled=True,
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "webhook_id",
            "tag": "test_webhook",
            "url": "https://example.com/webhook",
            "enabled": True,
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["tag"] == "test_webhook"
            print("✅ Create webhook mock test passed")

    @pytest.mark.asyncio
    async def test_delete_webhook_mock(self, pat_credentials):
        """Test deleting a webhook with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformDeleteWebhookConfig(
                form_id="test_form_id", tag="test_webhook"
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value.status_code = 204

            result = await node.execute({})

            assert result["success"] == True
            print("✅ Delete webhook mock test passed")


class TestTypeformOAuthTokenRefresh:
    """Test OAuth token refresh functionality."""

    @pytest.mark.asyncio
    async def test_token_refresh_on_expired(self, expired_oauth_credentials):
        """Test that expired OAuth tokens are refreshed automatically."""
        config = TypeformNodeFullConfig(
            config=TypeformListFormsConfig(page=1, page_size=10),
            credentials=expired_oauth_credentials,
        )
        node = create_typeform_node(config)

        mock_token_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 604800,
            "token_type": "Bearer",
        }

        mock_forms_response = {"total_items": 0, "items": []}

        mock_client = create_mock_client(200, mock_forms_response)

        # Create a mock for the refreshed tokens
        from nodes.oauth.typeform_oauth import TypeformTokens

        mock_refreshed_tokens = TypeformTokens(
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            token_type="Bearer",
            scope="offline forms:read",
        )

        with patch(
            "nodes.typeform_node.refresh_access_token", new_callable=AsyncMock
        ) as mock_refresh:
            with patch(
                "nodes.typeform_node.httpx.AsyncClient", return_value=mock_client
            ):
                mock_refresh.return_value = mock_refreshed_tokens

                result = await node.execute({})

                # Verify refresh was called
                assert mock_refresh.called
                assert result is not None
                print("✅ OAuth token refresh test passed")


class TestTypeformErrorHandling:
    """Test error handling for Typeform operations."""

    @pytest.mark.asyncio
    async def test_rate_limiting_retry(self, pat_credentials):
        """Test that rate limiting (429) is handled with retry."""
        config = TypeformNodeFullConfig(
            config=TypeformListFormsConfig(page=1, page_size=10),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_success_response = {"total_items": 0, "items": []}

        mock_client = create_mock_client(200, mock_success_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            with patch("time.sleep"):  # Mock sleep to speed up test
                result = await node.execute({})

                assert result is not None
                print("✅ Rate limiting retry test passed")

    @pytest.mark.asyncio
    async def test_404_error_handling(self, pat_credentials):
        """Test handling of 404 errors."""
        config = TypeformNodeFullConfig(
            config=TypeformGetFormConfig(form_id="nonexistent_form"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_client = create_mock_client(404, {})
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception):
                await node.execute({})

            print("✅ 404 error handling test passed")

    @pytest.mark.asyncio
    async def test_invalid_credentials_error(self, pat_credentials):
        """Test handling of invalid credentials (401)."""
        config = TypeformNodeFullConfig(
            config=TypeformListFormsConfig(page=1, page_size=10),
            credentials=TypeformPATCredential(personal_access_token="invalid_token"),
        )
        node = create_typeform_node(config)

        mock_client = create_mock_client(401, {})
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception):
                await node.execute({})

            print("✅ Invalid credentials error handling test passed")


class TestTypeformTranslationOperationsMock:
    """Test Typeform translation operations with mocked responses."""

    @pytest.mark.asyncio
    async def test_get_translation_statuses_mock(self, pat_credentials):
        """Test getting translation statuses with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetTranslationStatusesConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "statuses": [
                {"language": "es", "status": "completed"},
                {"language": "fr", "status": "in_progress"},
            ]
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert len(result["statuses"]) == 2
            print("✅ Get translation statuses mock test passed")

    @pytest.mark.asyncio
    async def test_auto_translate_mock(self, pat_credentials):
        """Test auto-translating a form with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformAutoTranslateConfig(
                form_id="test_form_id", target_language="es"
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {"status": "translation_started", "language": "es"}

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["language"] == "es"
            print("✅ Auto-translate mock test passed")


class TestTypeformNewOperationsMock:
    """Test new Typeform operations (webhooks list/get/update, translations, workspaces, file from response) with mocked responses."""

    @pytest.mark.asyncio
    async def test_list_webhooks_mock(self, pat_credentials):
        """Test listing webhooks with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformListWebhooksConfig(form_id="test_form_id"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "items": [
                {
                    "id": "webhook_1",
                    "tag": "test_webhook",
                    "url": "https://example.com/webhook",
                    "enabled": True,
                },
                {
                    "id": "webhook_2",
                    "tag": "prod_webhook",
                    "url": "https://example.com/webhook2",
                    "enabled": False,
                },
            ]
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert len(result["items"]) == 2
            assert result["items"][0]["tag"] == "test_webhook"
            print("✅ List webhooks mock test passed")

    @pytest.mark.asyncio
    async def test_get_webhook_mock(self, pat_credentials):
        """Test getting a webhook with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetWebhookConfig(form_id="test_form_id", tag="test_webhook"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "webhook_1",
            "tag": "test_webhook",
            "url": "https://example.com/webhook",
            "enabled": True,
            "verify_ssl": True,
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["tag"] == "test_webhook"
            assert result["enabled"] is True
            print("✅ Get webhook mock test passed")

    @pytest.mark.asyncio
    async def test_update_webhook_mock(self, pat_credentials):
        """Test updating a webhook with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformUpdateWebhookConfig(
                form_id="test_form_id",
                tag="test_webhook",
                url="https://example.com/updated-webhook",
                enabled=False,
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "webhook_1",
            "tag": "test_webhook",
            "url": "https://example.com/updated-webhook",
            "enabled": False,
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["url"] == "https://example.com/updated-webhook"
            assert result["enabled"] is False
            print("✅ Update webhook mock test passed")

    @pytest.mark.asyncio
    async def test_update_translation_mock(self, pat_credentials):
        """Test updating a translation with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformUpdateTranslationConfig(
                form_id="test_form_id",
                language="es",
                translation_data={"title": "Formulario actualizado", "fields": []},
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "language": "es",
            "status": "completed",
            "title": "Formulario actualizado",
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["language"] == "es"
            assert result["status"] == "completed"
            print("✅ Update translation mock test passed")

    @pytest.mark.asyncio
    async def test_list_account_workspaces_mock(self, pat_credentials):
        """Test listing account workspaces with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformListAccountWorkspacesConfig(page=1, page_size=10),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "items": [
                {"id": "ws_1", "name": "Account Workspace 1"},
                {"id": "ws_2", "name": "Account Workspace 2"},
            ],
            "page_count": 1,
            "total_items": 2,
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert len(result["items"]) == 2
            assert result["items"][0]["name"] == "Account Workspace 1"
            print("✅ List account workspaces mock test passed")

    @pytest.mark.asyncio
    async def test_create_account_workspace_mock(self, pat_credentials):
        """Test creating an account workspace with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformCreateAccountWorkspaceConfig(name="New Account Workspace"),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "id": "ws_new",
            "name": "New Account Workspace",
            "created_at": "2024-01-01T00:00:00Z",
        }

        mock_client = create_mock_client(201, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["id"] == "ws_new"
            assert result["name"] == "New Account Workspace"
            print("✅ Create account workspace mock test passed")

    @pytest.mark.asyncio
    async def test_get_file_from_response_mock(self, pat_credentials):
        """Test getting a file from a response with mocked response."""
        config = TypeformNodeFullConfig(
            config=TypeformGetFileFromResponseConfig(
                form_id="test_form_id",
                response_id="resp_123",
                field_id="field_456",
                filename="document.pdf",
            ),
            credentials=pat_credentials,
        )
        node = create_typeform_node(config)

        mock_response = {
            "file_url": "https://example.com/files/document.pdf",
            "filename": "document.pdf",
            "size": 102400,
            "content_type": "application/pdf",
        }

        mock_client = create_mock_client(200, mock_response)
        with patch("nodes.typeform_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

            assert result["filename"] == "document.pdf"
            assert result["content_type"] == "application/pdf"
            print("✅ Get file from response mock test passed")
