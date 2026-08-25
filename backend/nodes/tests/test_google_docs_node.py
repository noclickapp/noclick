"""
Mock tests for Google Docs workflow node.

Tests Google Docs operations with mocked HTTP responses:
- Documents: list_documents, get_document, create_document, append_text, insert_text, replace_text

Uses httpx mocking to simulate Google Docs API responses without real credentials.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.google_docs_node import (
    GoogleDocsNode,
    GoogleDocsNodeConfig,
    GoogleDocsOAuthCredential,
    # Document operations
    GoogleDocsListDocumentsConfig,
    GoogleDocsGetDocumentConfig,
    GoogleDocsCreateDocumentConfig,
    GoogleDocsAppendTextConfig,
    GoogleDocsInsertTextConfig,
    GoogleDocsReplaceTextConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

TEST_CREDENTIALS = GoogleDocsOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",
    email="test@example.com",
)


def create_node(config) -> GoogleDocsNode:
    """Create a GoogleDocsNode instance with the given config."""
    node_config = GoogleDocsNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return GoogleDocsNode(
        node_id="test-node",
        node_type="automation-google-docs",
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
# Document Operations Tests
# ============================================================================


class TestListDocuments:
    """Test list_documents operation."""

    @pytest.mark.asyncio
    async def test_list_documents_success(self):
        """Test listing documents returns documents successfully."""
        config = GoogleDocsListDocumentsConfig(page_size=50)
        node = create_node(config)

        mock_files = {
            "files": [
                {
                    "id": "doc123",
                    "name": "Project Proposal",
                    "mimeType": "application/vnd.google-apps.document",
                    "createdTime": "2024-01-10T10:00:00Z",
                    "modifiedTime": "2024-01-15T14:30:00Z",
                    "webViewLink": "https://docs.google.com/document/d/doc123/edit",
                },
                {
                    "id": "doc456",
                    "name": "Meeting Notes",
                    "mimeType": "application/vnd.google-apps.document",
                    "createdTime": "2024-01-12T09:00:00Z",
                    "modifiedTime": "2024-01-14T16:00:00Z",
                    "webViewLink": "https://docs.google.com/document/d/doc456/edit",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_google_drive_documents"
            assert result["document_count"] == 2
            assert len(result["documents"]) == 2

    @pytest.mark.asyncio
    async def test_list_documents_empty(self):
        """Test listing documents when none exist."""
        config = GoogleDocsListDocumentsConfig()
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"files": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["document_count"] == 0
            assert result["documents"] == []


class TestGetDocument:
    """Test get_document operation."""

    @pytest.mark.asyncio
    async def test_get_document_success(self):
        """Test getting a single document."""
        config = GoogleDocsGetDocumentConfig(document_id="doc123", include_content=True)
        node = create_node(config)

        mock_document = {
            "documentId": "doc123",
            "title": "My Document",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": "Hello, World!\n"}}]
                        }
                    }
                ]
            },
            "revisionId": "revision123",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_document)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_document_content"
            assert "document" in result


class TestCreateDocument:
    """Test create_document operation."""

    @pytest.mark.asyncio
    async def test_create_document_success(self):
        """Test creating a new document."""
        config = GoogleDocsCreateDocumentConfig(
            title="New Document", initial_content="This is the initial content."
        )
        node = create_node(config)

        mock_created = {
            "documentId": "new_doc_id",
            "title": "New Document",
            "revisionId": "revision1",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_document"
            assert result["document_id"] == "new_doc_id"

    @pytest.mark.asyncio
    async def test_create_document_empty(self):
        """Test creating an empty document."""
        config = GoogleDocsCreateDocumentConfig(title="Empty Document")
        node = create_node(config)

        mock_created = {
            "documentId": "empty_doc_id",
            "title": "Empty Document",
            "revisionId": "revision1",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"


class TestAppendText:
    """Test append_text operation."""

    @pytest.mark.asyncio
    async def test_append_text_success(self):
        """Test appending text to a document."""
        config = GoogleDocsAppendTextConfig(
            document_id="doc123", text="This text will be appended."
        )
        node = create_node(config)

        # Mock both GET (to get document) and POST (to update)
        mock_doc = {"documentId": "doc123", "body": {"content": [{"endIndex": 100}]}}
        mock_result = {
            "documentId": "doc123",
            "replies": [{}],
            "writeControl": {"requiredRevisionId": "revision2"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_doc)
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "append_text_to_document"
            assert result["document_id"] == "doc123"


class TestInsertText:
    """Test insert_text operation."""

    @pytest.mark.asyncio
    async def test_insert_text_success(self):
        """Test inserting text into a document."""
        config = GoogleDocsInsertTextConfig(
            document_id="doc123", text="Hello, World!", index=1
        )
        node = create_node(config)

        mock_result = {
            "documentId": "doc123",
            "replies": [{}],
            "writeControl": {"requiredRevisionId": "revision3"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "insert_text_in_document"
            assert result["document_id"] == "doc123"


class TestReplaceText:
    """Test replace_text operation."""

    @pytest.mark.asyncio
    async def test_replace_text_success(self):
        """Test replacing text in a document."""
        config = GoogleDocsReplaceTextConfig(
            document_id="doc123",
            find_text="old text",
            replace_with="new text",
            match_case=True,
        )
        node = create_node(config)

        mock_result = {
            "documentId": "doc123",
            "replies": [{"replaceAllText": {"occurrencesChanged": 3}}],
            "writeControl": {"requiredRevisionId": "revision4"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_result)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "replace_document_text"
            assert result["occurrences_changed"] == 3


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_not_found(self):
        """Test handling of 404 errors."""
        config = GoogleDocsGetDocumentConfig(document_id="nonexistent")
        node = create_node(config)

        error_response = {"error": {"code": 404, "message": "Document not found"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, error_response, "Document not found"
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
        config = GoogleDocsGetDocumentConfig(document_id="protected_doc")
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
    async def test_load_document_options(self):
        """Test loading document options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
            "email": "test@example.com",
        }

        mock_files = {
            "files": [
                {"id": "doc1", "name": "Document 1"},
                {"id": "doc2", "name": "Document 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_files)

            result = await GoogleDocsNode.load_field_options(
                "document_id", credential_data, None
            )

            # Dynamic options return a list
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["value"] == "doc1"
            assert result[0]["label"] == "Document 1"
