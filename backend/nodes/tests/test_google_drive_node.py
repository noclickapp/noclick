"""
Unit tests for Google Drive node.

Tests the Google Drive node functionality with mocked API responses.
All 40 operations are tested covering files, trash, permissions, comments, replies,
revisions, shared drives, and account info.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from nodes.google_drive_node import (
    GoogleDriveNode,
    GoogleDriveNodeConfig,
    GoogleDriveOAuthCredential,
    GoogleDriveOnFileChangedConfig,
    # File operations
    GoogleDriveListConfig,
    GoogleDriveGetConfig,
    GoogleDriveDownloadConfig,
    GoogleDriveCreateFolderConfig,
    GoogleDriveUploadConfig,
    GoogleDriveCopyConfig,
    GoogleDriveMoveConfig,
    GoogleDriveDeleteConfig,
    GoogleDriveUpdateConfig,
    GoogleDriveSearchConfig,
    GoogleDriveExportConfig,
    # Trash operations
    GoogleDriveTrashConfig,
    GoogleDriveRestoreConfig,
    GoogleDriveEmptyTrashConfig,
    # Permission operations
    GoogleDriveShareConfig,
    GoogleDriveUnshareConfig,
    GoogleDriveListPermissionsConfig,
    GoogleDriveGetPermissionConfig,
    GoogleDriveUpdatePermissionConfig,
    # Comment operations
    GoogleDriveCreateCommentConfig,
    GoogleDriveListCommentsConfig,
    GoogleDriveGetCommentConfig,
    GoogleDriveUpdateCommentConfig,
    GoogleDriveDeleteCommentConfig,
    # Reply operations
    GoogleDriveCreateReplyConfig,
    GoogleDriveListRepliesConfig,
    GoogleDriveGetReplyConfig,
    GoogleDriveUpdateReplyConfig,
    GoogleDriveDeleteReplyConfig,
    # Revision operations
    GoogleDriveListRevisionsConfig,
    GoogleDriveGetRevisionConfig,
    GoogleDriveUpdateRevisionConfig,
    GoogleDriveDeleteRevisionConfig,
    # Shared Drive operations
    GoogleDriveListSharedDrivesConfig,
    GoogleDriveGetSharedDriveConfig,
    GoogleDriveCreateSharedDriveConfig,
    GoogleDriveDeleteSharedDriveConfig,
    GoogleDriveHideSharedDriveConfig,
    GoogleDriveUnhideSharedDriveConfig,
    # Account operations
    GoogleDriveGetAboutConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return GoogleDriveOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create_response(status_code: int, json_data: dict):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data
        response.text = json.dumps(json_data)
        response.content = json.dumps(json_data).encode()
        return response

    return _create_response


def create_node(config, credentials) -> GoogleDriveNode:
    """Create a GoogleDriveNode instance with the given config."""
    node_config = GoogleDriveNodeConfig(config=config, credentials=credentials)
    return GoogleDriveNode(
        node_id="test-node",
        node_type="automation-google-drive",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


# ============================================================================
# List Operation Tests
# ============================================================================


class TestListOperation:
    """Test Google Drive list operation."""

    @pytest.mark.asyncio
    async def test_list_files_success(self, mock_credentials, mock_httpx_response):
        """Test listing files returns correct structure."""
        config = GoogleDriveListConfig(page_size=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {"id": "file1", "name": "Document.txt", "mimeType": "text/plain"},
                    {
                        "id": "file2",
                        "name": "Folder",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ],
                "nextPageToken": None,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_files"
            assert "files" in result
            assert len(result["files"]) == 2
            assert result["file_count"] == 2

    @pytest.mark.asyncio
    async def test_list_files_with_folder_filter(
        self, mock_credentials, mock_httpx_response
    ):
        """Test listing files in a specific folder."""
        config = GoogleDriveListConfig(folder_id="folder123", page_size=5)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"files": [], "nextPageToken": None})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["file_count"] == 0

    @pytest.mark.asyncio
    async def test_list_files_api_error(self, mock_credentials, mock_httpx_response):
        """Test handling of API errors during list."""
        config = GoogleDriveListConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            403, {"error": {"message": "Access denied"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="Google Drive API error"):
                await node.execute({})


# ============================================================================
# Get Operation Tests
# ============================================================================


class TestGetOperation:
    """Test Google Drive get file metadata operation."""

    @pytest.mark.asyncio
    async def test_get_file_metadata_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting file metadata."""
        config = GoogleDriveGetConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "file123",
                "name": "test.txt",
                "mimeType": "text/plain",
                "size": "1024",
                "createdTime": "2024-01-01T00:00:00Z",
                "modifiedTime": "2024-01-02T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_file_metadata"
            assert result["file_id"] == "file123"
            assert result["file"]["name"] == "test.txt"

    @pytest.mark.asyncio
    async def test_get_nonexistent_file(self, mock_credentials, mock_httpx_response):
        """Test getting a nonexistent file returns error."""
        config = GoogleDriveGetConfig(file_id="nonexistent")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            404, {"error": {"message": "File not found"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="Google Drive API error"):
                await node.execute({})


# ============================================================================
# Download Operation Tests
# ============================================================================


class TestDownloadOperation:
    """Test Google Drive download operation."""

    @pytest.mark.asyncio
    async def test_download_text_file(self, mock_credentials, mock_httpx_response):
        """Text content stays decoded inline (text branch untouched)."""
        config = GoogleDriveDownloadConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        # First call gets metadata, second downloads content
        metadata_response = mock_httpx_response(
            200, {"id": "file123", "name": "test.txt", "mimeType": "text/plain"}
        )
        content_response = MagicMock()
        content_response.status_code = 200
        content_response.content = b"Hello, World!"
        content_response.text = "Hello, World!"
        content_response.headers = {"content-type": "text/plain"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[metadata_response, content_response]
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "download_file"
            # Text content is decoded inline, not stored as a binary reference
            assert result["content"] == "Hello, World!"
            assert result["encoding"] == "text"

    @pytest.mark.asyncio
    async def test_download_google_doc_as_pdf(
        self, mock_credentials, mock_httpx_response
    ):
        """Test exporting Google Doc as PDF."""
        config = GoogleDriveDownloadConfig(file_id="doc123", export_format="pdf")
        node = create_node(config, mock_credentials)
        node.user_id = "test-user"

        metadata_response = mock_httpx_response(
            200,
            {
                "id": "doc123",
                "name": "Document",
                "mimeType": "application/vnd.google-apps.document",
            },
        )
        content_response = MagicMock()
        content_response.status_code = 200
        content_response.content = b"%PDF-1.4..."
        content_response.headers = {"content-type": "application/pdf"}

        resolved_ref = {
            "download_url": "https://r2.example/doc.pdf",
            "mime_type": "application/pdf",
            "name": "Document",
            "size_bytes": len(b"%PDF-1.4..."),
        }

        with patch("httpx.AsyncClient") as mock_client, patch(
            "nodes.core.binary_output.create_resource_from_bytes",
            new=AsyncMock(return_value=resolved_ref),
        ) as mock_store:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[metadata_response, content_response]
            )

            result = await node.run({})

            assert result["status"] == "success"
            assert result["operation"] == "download_file"
            # Binary content resolves to a stored file reference
            assert result["content"]["url"] == "https://r2.example/doc.pdf"
            assert result["content"]["mime_type"] == "application/pdf"
            assert result["content"]["size_bytes"] == len(b"%PDF-1.4...")
            assert mock_store.await_args.kwargs["body"] == b"%PDF-1.4..."
            assert mock_store.await_args.kwargs["content_type"] == "application/pdf"


# ============================================================================
# Create Folder Operation Tests
# ============================================================================


class TestCreateFolderOperation:
    """Test Google Drive create folder operation."""

    @pytest.mark.asyncio
    async def test_create_folder_success(self, mock_credentials, mock_httpx_response):
        """Test creating a folder."""
        config = GoogleDriveCreateFolderConfig(folder_name="New Folder")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "folder123",
                "name": "New Folder",
                "mimeType": "application/vnd.google-apps.folder",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_folder"
            assert result["folder_name"] == "New Folder"
            assert result["folder_id"] == "folder123"

    @pytest.mark.asyncio
    async def test_create_folder_with_parent(
        self, mock_credentials, mock_httpx_response
    ):
        """Test creating a folder inside another folder."""
        config = GoogleDriveCreateFolderConfig(
            folder_name="Subfolder", parent_folder_id="parent123"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "subfolder123",
                "name": "Subfolder",
                "mimeType": "application/vnd.google-apps.folder",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["folder_id"] == "subfolder123"


# ============================================================================
# Upload Operation Tests
# ============================================================================


class TestUploadOperation:
    """Test Google Drive upload operation."""

    @pytest.mark.asyncio
    async def test_upload_text_file(self, mock_credentials, mock_httpx_response):
        """Test uploading a text file."""
        config = GoogleDriveUploadConfig(
            file_name="test.txt", content="Hello, World!", mime_type="text/plain"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "newfile123", "name": "test.txt", "mimeType": "text/plain"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "upload_file"
            assert result["file_name"] == "test.txt"
            assert result["file_id"] == "newfile123"

    @pytest.mark.asyncio
    async def test_upload_base64_file(self, mock_credentials, mock_httpx_response):
        """Test uploading a base64-encoded file."""
        import base64

        content = base64.b64encode(b"Binary content").decode()

        config = GoogleDriveUploadConfig(
            file_name="binary.bin", content=content, is_base64=True
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "binary123", "name": "binary.bin"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["file_id"] == "binary123"


# ============================================================================
# Copy Operation Tests
# ============================================================================


class TestCopyOperation:
    """Test Google Drive copy operation."""

    @pytest.mark.asyncio
    async def test_copy_file_success(self, mock_credentials, mock_httpx_response):
        """Test copying a file."""
        config = GoogleDriveCopyConfig(file_id="source123", new_name="Copy of Document")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "copy123", "name": "Copy of Document"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "copy_file"
            assert result["original_file_id"] == "source123"
            assert result["new_file_id"] == "copy123"

    @pytest.mark.asyncio
    async def test_copy_file_to_folder(self, mock_credentials, mock_httpx_response):
        """Test copying a file to a specific folder."""
        config = GoogleDriveCopyConfig(
            file_id="source123", destination_folder_id="dest_folder"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "copy456", "name": "Copy of original"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["new_file_id"] == "copy456"


# ============================================================================
# Move Operation Tests
# ============================================================================


class TestMoveOperation:
    """Test Google Drive move operation."""

    @pytest.mark.asyncio
    async def test_move_file_success(self, mock_credentials, mock_httpx_response):
        """Test moving a file to another folder."""
        config = GoogleDriveMoveConfig(
            file_id="file123", destination_folder_id="folder456"
        )
        node = create_node(config, mock_credentials)

        # Move operation: GET current parents, then PATCH to update
        get_response = mock_httpx_response(
            200, {"id": "file123", "name": "file.txt", "parents": ["old_folder"]}
        )
        patch_response = mock_httpx_response(
            200, {"id": "file123", "name": "file.txt", "parents": ["folder456"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=get_response)
            mock_instance.patch = AsyncMock(return_value=patch_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "move_file"
            assert result["file_id"] == "file123"
            assert result["to_folder"] == "folder456"


# ============================================================================
# Delete Operation Tests
# ============================================================================


class TestDeleteOperation:
    """Test Google Drive delete operation."""

    @pytest.mark.asyncio
    async def test_delete_file_success(self, mock_credentials, mock_httpx_response):
        """Test deleting a file."""
        config = GoogleDriveDeleteConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204  # No content on successful delete

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_file"
            assert result["file_id"] == "file123"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, mock_credentials, mock_httpx_response):
        """Test deleting a nonexistent file."""
        config = GoogleDriveDeleteConfig(file_id="nonexistent")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            404, {"error": {"message": "File not found"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="Google Drive API error"):
                await node.execute({})


# ============================================================================
# Share Operation Tests
# ============================================================================


class TestShareOperation:
    """Test Google Drive share operation."""

    @pytest.mark.asyncio
    async def test_share_file_anyone(self, mock_credentials, mock_httpx_response):
        """Test sharing a file with anyone."""
        config = GoogleDriveShareConfig(
            file_id="file123", share_type="anyone", role="reader"
        )
        node = create_node(config, mock_credentials)

        permission_response = mock_httpx_response(
            200, {"id": "perm123", "type": "anyone", "role": "reader"}
        )
        file_response = mock_httpx_response(
            200, {"webViewLink": "https://drive.google.com/file/d/file123/view"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=permission_response)
            mock_instance.get = AsyncMock(return_value=file_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "share_file"
            assert result["share_type"] == "anyone"
            assert result["role"] == "reader"
            assert "web_link" in result

    @pytest.mark.asyncio
    async def test_share_file_with_user(self, mock_credentials, mock_httpx_response):
        """Test sharing a file with a specific user."""
        config = GoogleDriveShareConfig(
            file_id="file123",
            share_type="user",
            email="user@example.com",
            role="writer",
        )
        node = create_node(config, mock_credentials)

        permission_response = mock_httpx_response(
            200,
            {
                "id": "perm456",
                "type": "user",
                "role": "writer",
                "emailAddress": "user@example.com",
            },
        )
        file_response = mock_httpx_response(
            200, {"webViewLink": "https://drive.google.com/file/d/file123/view"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=permission_response)
            mock_instance.get = AsyncMock(return_value=file_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["share_type"] == "user"
            assert result["role"] == "writer"


# ============================================================================
# Export Operation Tests
# ============================================================================


class TestExportOperation:
    """Test Google Drive export operation for Google Workspace files."""

    @pytest.mark.asyncio
    async def test_export_google_doc_to_pdf(
        self, mock_credentials, mock_httpx_response
    ):
        """Test exporting Google Doc to PDF."""
        config = GoogleDriveExportConfig(file_id="doc123", export_format="pdf")
        node = create_node(config, mock_credentials)
        node.user_id = "test-user"

        metadata_response = mock_httpx_response(
            200,
            {
                "id": "doc123",
                "name": "Document",
                "mimeType": "application/vnd.google-apps.document",
            },
        )
        content_response = MagicMock()
        content_response.status_code = 200
        content_response.content = b"%PDF-1.4..."

        resolved_ref = {
            "download_url": "https://r2.example/Document.pdf",
            "mime_type": "application/pdf",
            "name": "Document.pdf",
            "size_bytes": len(b"%PDF-1.4..."),
        }

        with patch("httpx.AsyncClient") as mock_client, patch(
            "nodes.core.binary_output.create_resource_from_bytes",
            new=AsyncMock(return_value=resolved_ref),
        ) as mock_store:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[metadata_response, content_response]
            )

            result = await node.run({})

            assert result["status"] == "success"
            assert result["operation"] == "export_google_workspace_file"
            assert result["export_format"] == "pdf"
            # Exported bytes resolve to a stored file reference
            assert result["content"]["url"] == "https://r2.example/Document.pdf"
            assert result["content"]["mime_type"] == "application/pdf"
            assert mock_store.await_args.kwargs["body"] == b"%PDF-1.4..."
            assert mock_store.await_args.kwargs["content_type"] == "application/pdf"
            assert mock_store.await_args.kwargs["filename"] == "Document.pdf"

    @pytest.mark.asyncio
    async def test_export_spreadsheet_to_csv(
        self, mock_credentials, mock_httpx_response
    ):
        """Test exporting Google Spreadsheet to CSV."""
        config = GoogleDriveExportConfig(file_id="sheet123", export_format="csv")
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200,
            {
                "id": "sheet123",
                "name": "Spreadsheet",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            },
        )
        content_response = MagicMock()
        content_response.status_code = 200
        content_response.content = b"col1,col2\nval1,val2"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[metadata_response, content_response]
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "export_google_workspace_file"


# ============================================================================
# Update Operation Tests
# ============================================================================


class TestUpdateOperation:
    """Test Google Drive update/rename operation."""

    @pytest.mark.asyncio
    async def test_update_file_name(self, mock_credentials, mock_httpx_response):
        """Test renaming a file."""
        config = GoogleDriveUpdateConfig(file_id="file123", new_name="Renamed File.txt")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "file123", "name": "Renamed File.txt", "mimeType": "text/plain"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_file_metadata"
            assert result["file_id"] == "file123"
            assert result["file"]["name"] == "Renamed File.txt"

    @pytest.mark.asyncio
    async def test_update_file_starred(self, mock_credentials, mock_httpx_response):
        """Test starring a file."""
        config = GoogleDriveUpdateConfig(file_id="file123", starred=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "file123", "name": "File.txt", "starred": True}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_file_metadata"


# ============================================================================
# Trash Operation Tests
# ============================================================================


class TestTrashOperation:
    """Test Google Drive trash operation."""

    @pytest.mark.asyncio
    async def test_trash_file(self, mock_credentials, mock_httpx_response):
        """Test moving a file to trash."""
        config = GoogleDriveTrashConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "file123", "name": "File.txt", "trashed": True}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "move_file_to_trash"
            assert result["file_id"] == "file123"


# ============================================================================
# Restore Operation Tests
# ============================================================================


class TestRestoreOperation:
    """Test Google Drive restore from trash operation."""

    @pytest.mark.asyncio
    async def test_restore_file(self, mock_credentials, mock_httpx_response):
        """Test restoring a file from trash."""
        config = GoogleDriveRestoreConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "file123", "name": "File.txt", "trashed": False}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "restore_file_from_trash"
            assert result["file_id"] == "file123"


# ============================================================================
# Empty Trash Operation Tests
# ============================================================================


class TestEmptyTrashOperation:
    """Test Google Drive empty trash operation."""

    @pytest.mark.asyncio
    async def test_empty_trash(self, mock_credentials, mock_httpx_response):
        """Test emptying trash."""
        config = GoogleDriveEmptyTrashConfig(confirm=True)
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204  # No content on success

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "empty_drive_trash"

    @pytest.mark.asyncio
    async def test_empty_trash_requires_confirmation(self, mock_credentials):
        """Test that empty_trash requires confirmation."""
        config = GoogleDriveEmptyTrashConfig(confirm=False)
        node = create_node(config, mock_credentials)

        with pytest.raises(ValueError, match="confirm"):
            await node.execute({})


# ============================================================================
# Unshare Operation Tests
# ============================================================================


class TestUnshareOperation:
    """Test Google Drive unshare/remove permission operation."""

    @pytest.mark.asyncio
    async def test_unshare_file(self, mock_credentials, mock_httpx_response):
        """Test removing a permission from a file."""
        config = GoogleDriveUnshareConfig(file_id="file123", permission_id="perm456")
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "remove_file_permission"
            assert result["file_id"] == "file123"
            assert "perm456" in result["removed_permissions"]


# ============================================================================
# List Permissions Operation Tests
# ============================================================================


class TestListPermissionsOperation:
    """Test Google Drive list permissions operation."""

    @pytest.mark.asyncio
    async def test_list_permissions(self, mock_credentials, mock_httpx_response):
        """Test listing file permissions."""
        config = GoogleDriveListPermissionsConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "permissions": [
                    {
                        "id": "perm1",
                        "type": "user",
                        "role": "owner",
                        "emailAddress": "owner@example.com",
                    },
                    {"id": "perm2", "type": "anyone", "role": "reader"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_file_permissions"
            assert result["file_id"] == "file123"
            assert len(result["permissions"]) == 2


# ============================================================================
# Search Operation Tests
# ============================================================================


class TestSearchOperation:
    """Test Google Drive search operation."""

    @pytest.mark.asyncio
    async def test_search_files(self, mock_credentials, mock_httpx_response):
        """Test searching for files."""
        config = GoogleDriveSearchConfig(query="name contains 'report'")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "file1",
                        "name": "Q1 Report.pdf",
                        "mimeType": "application/pdf",
                    },
                    {
                        "id": "file2",
                        "name": "Annual Report.docx",
                        "mimeType": "application/msword",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "search_files"
            assert len(result["files"]) == 2
            assert result["file_count"] == 2


# ============================================================================
# Comment Operations Tests
# ============================================================================


class TestCommentOperations:
    """Test Google Drive comment operations."""

    @pytest.mark.asyncio
    async def test_create_comment(self, mock_credentials, mock_httpx_response):
        """Test creating a comment on a file."""
        config = GoogleDriveCreateCommentConfig(
            file_id="file123", content="This is a comment"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "comment123",
                "content": "This is a comment",
                "author": {"displayName": "Test User"},
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_file_comment"
            assert result["file_id"] == "file123"
            assert result["comment"]["content"] == "This is a comment"

    @pytest.mark.asyncio
    async def test_list_comments(self, mock_credentials, mock_httpx_response):
        """Test listing comments on a file."""
        config = GoogleDriveListCommentsConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "comments": [
                    {"id": "comment1", "content": "First comment"},
                    {"id": "comment2", "content": "Second comment"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_file_comments"
            assert len(result["comments"]) == 2

    @pytest.mark.asyncio
    async def test_delete_comment(self, mock_credentials, mock_httpx_response):
        """Test deleting a comment."""
        config = GoogleDriveDeleteCommentConfig(
            file_id="file123", comment_id="comment456"
        )
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_file_comment"
            assert result["file_id"] == "file123"
            assert result["comment_id"] == "comment456"

    @pytest.mark.asyncio
    async def test_get_comment(self, mock_credentials, mock_httpx_response):
        """Test getting a specific comment."""
        config = GoogleDriveGetCommentConfig(file_id="file123", comment_id="comment456")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "comment456",
                "content": "This is a comment",
                "author": {"displayName": "Test User"},
                "createdTime": "2024-01-01T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_file_comment"
            assert result["comment"]["id"] == "comment456"

    @pytest.mark.asyncio
    async def test_update_comment(self, mock_credentials, mock_httpx_response):
        """Test updating a comment."""
        config = GoogleDriveUpdateCommentConfig(
            file_id="file123",
            comment_id="comment456",
            content="Updated comment content",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "comment456",
                "content": "Updated comment content",
                "modifiedTime": "2024-01-02T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_file_comment"
            assert result["comment"]["content"] == "Updated comment content"


# ============================================================================
# Reply Operations Tests
# ============================================================================


class TestReplyOperations:
    """Test Google Drive reply operations."""

    @pytest.mark.asyncio
    async def test_create_reply(self, mock_credentials, mock_httpx_response):
        """Test creating a reply to a comment."""
        config = GoogleDriveCreateReplyConfig(
            file_id="file123", comment_id="comment456", content="This is a reply"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "reply789",
                "content": "This is a reply",
                "author": {"displayName": "Test User"},
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_comment_reply"
            assert result["reply"]["content"] == "This is a reply"

    @pytest.mark.asyncio
    async def test_list_replies(self, mock_credentials, mock_httpx_response):
        """Test listing replies to a comment."""
        config = GoogleDriveListRepliesConfig(
            file_id="file123", comment_id="comment456"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "replies": [
                    {"id": "reply1", "content": "First reply"},
                    {"id": "reply2", "content": "Second reply"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_comment_replies"
            assert len(result["replies"]) == 2

    @pytest.mark.asyncio
    async def test_get_reply(self, mock_credentials, mock_httpx_response):
        """Test getting a specific reply."""
        config = GoogleDriveGetReplyConfig(
            file_id="file123", comment_id="comment456", reply_id="reply789"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "reply789",
                "content": "This is a reply",
                "author": {"displayName": "Test User"},
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_comment_reply"
            assert result["reply"]["id"] == "reply789"

    @pytest.mark.asyncio
    async def test_update_reply(self, mock_credentials, mock_httpx_response):
        """Test updating a reply."""
        config = GoogleDriveUpdateReplyConfig(
            file_id="file123",
            comment_id="comment456",
            reply_id="reply789",
            content="Updated reply content",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "reply789",
                "content": "Updated reply content",
                "modifiedTime": "2024-01-02T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_comment_reply"
            assert result["reply"]["content"] == "Updated reply content"

    @pytest.mark.asyncio
    async def test_delete_reply(self, mock_credentials, mock_httpx_response):
        """Test deleting a reply."""
        config = GoogleDriveDeleteReplyConfig(
            file_id="file123", comment_id="comment456", reply_id="reply789"
        )
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_comment_reply"
            assert result["reply_id"] == "reply789"


# ============================================================================
# Revision Operations Tests
# ============================================================================


class TestRevisionOperations:
    """Test Google Drive revision operations."""

    @pytest.mark.asyncio
    async def test_list_revisions(self, mock_credentials, mock_httpx_response):
        """Test listing file revisions."""
        config = GoogleDriveListRevisionsConfig(file_id="file123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "revisions": [
                    {"id": "rev1", "modifiedTime": "2024-01-01T00:00:00Z"},
                    {"id": "rev2", "modifiedTime": "2024-01-02T00:00:00Z"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_file_revisions"
            assert result["file_id"] == "file123"
            assert len(result["revisions"]) == 2

    @pytest.mark.asyncio
    async def test_get_revision(self, mock_credentials, mock_httpx_response):
        """Test getting a specific revision."""
        config = GoogleDriveGetRevisionConfig(file_id="file123", revision_id="rev456")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "rev456",
                "mimeType": "application/pdf",
                "modifiedTime": "2024-01-01T00:00:00Z",
                "size": "12345",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_file_revision"
            assert result["revision"]["id"] == "rev456"

    @pytest.mark.asyncio
    async def test_update_revision(self, mock_credentials, mock_httpx_response):
        """Test updating a revision."""
        config = GoogleDriveUpdateRevisionConfig(
            file_id="file123", revision_id="rev456", keep_forever=True
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "rev456",
                "keepForever": True,
                "modifiedTime": "2024-01-01T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_file_revision"
            assert result["revision"]["keepForever"] is True

    @pytest.mark.asyncio
    async def test_delete_revision(self, mock_credentials, mock_httpx_response):
        """Test deleting a revision."""
        config = GoogleDriveDeleteRevisionConfig(
            file_id="file123", revision_id="rev456"
        )
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_file_revision"
            assert result["revision_id"] == "rev456"


# ============================================================================
# Permission Operations Tests
# ============================================================================


class TestPermissionOperations:
    """Test Google Drive permission operations."""

    @pytest.mark.asyncio
    async def test_get_permission(self, mock_credentials, mock_httpx_response):
        """Test getting a specific permission."""
        config = GoogleDriveGetPermissionConfig(
            file_id="file123", permission_id="perm456"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "perm456",
                "type": "user",
                "role": "writer",
                "emailAddress": "user@example.com",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_file_permission"
            assert result["permission"]["role"] == "writer"

    @pytest.mark.asyncio
    async def test_update_permission(self, mock_credentials, mock_httpx_response):
        """Test updating a permission."""
        config = GoogleDriveUpdatePermissionConfig(
            file_id="file123", permission_id="perm456", role="reader"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "perm456",
                "type": "user",
                "role": "reader",
                "emailAddress": "user@example.com",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_file_permission"
            assert result["permission"]["role"] == "reader"


# ============================================================================
# Shared Drive Operations Tests
# ============================================================================


class TestSharedDriveOperations:
    """Test Google Drive shared drive operations."""

    @pytest.mark.asyncio
    async def test_list_shared_drives(self, mock_credentials, mock_httpx_response):
        """Test listing shared drives."""
        config = GoogleDriveListSharedDrivesConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "drives": [
                    {"id": "drive1", "name": "Team Drive 1"},
                    {"id": "drive2", "name": "Team Drive 2"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_shared_drives"
            assert len(result["drives"]) == 2

    @pytest.mark.asyncio
    async def test_get_shared_drive(self, mock_credentials, mock_httpx_response):
        """Test getting a shared drive."""
        config = GoogleDriveGetSharedDriveConfig(drive_id="drive123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "drive123",
                "name": "Team Drive",
                "createdTime": "2024-01-01T00:00:00Z",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_shared_drive"
            assert result["drive"]["name"] == "Team Drive"

    @pytest.mark.asyncio
    async def test_create_shared_drive(self, mock_credentials, mock_httpx_response):
        """Test creating a shared drive."""
        config = GoogleDriveCreateSharedDriveConfig(name="New Team Drive")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "newdrive123", "name": "New Team Drive"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_shared_drive"
            assert result["drive"]["name"] == "New Team Drive"

    @pytest.mark.asyncio
    async def test_delete_shared_drive(self, mock_credentials, mock_httpx_response):
        """Test deleting a shared drive."""
        config = GoogleDriveDeleteSharedDriveConfig(drive_id="drive123")
        node = create_node(config, mock_credentials)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_shared_drive"
            assert result["drive_id"] == "drive123"

    @pytest.mark.asyncio
    async def test_hide_shared_drive(self, mock_credentials, mock_httpx_response):
        """Test hiding a shared drive."""
        config = GoogleDriveHideSharedDriveConfig(drive_id="drive123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "drive123", "name": "Team Drive", "hidden": True}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "hide_shared_drive"

    @pytest.mark.asyncio
    async def test_unhide_shared_drive(self, mock_credentials, mock_httpx_response):
        """Test unhiding a shared drive."""
        config = GoogleDriveUnhideSharedDriveConfig(drive_id="drive123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "drive123", "name": "Team Drive", "hidden": False}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "unhide_shared_drive"


# ============================================================================
# Get About Operation Tests
# ============================================================================


class TestGetAboutOperation:
    """Test Google Drive get about/quota operation."""

    @pytest.mark.asyncio
    async def test_get_about(self, mock_credentials, mock_httpx_response):
        """Test getting Drive account info and quota."""
        config = GoogleDriveGetAboutConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "user": {
                    "displayName": "Test User",
                    "emailAddress": "test@example.com",
                },
                "storageQuota": {
                    "limit": "16106127360",
                    "usage": "5000000000",
                    "usageInDrive": "4500000000",
                    "usageInDriveTrash": "500000000",
                },
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_drive_storage_info"
            assert "user" in result
            assert "storage" in result
            assert result["user"]["email"] == "test@example.com"
            assert result["storage"]["limit"] == 16106127360


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = GoogleDriveListConfig()
        node_config = GoogleDriveNodeConfig(config=config, credentials=None)
        node = GoogleDriveNode(
            node_id="test-node",
            node_type="automation-google-drive",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_config(self):
        """Test handling of missing config."""
        node = GoogleDriveNode(
            node_id="test-node",
            node_type="automation-google-drive",
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Configuration is required"):
            await node.execute({})


# ============================================================================
# Dynamic Options Tests
# ============================================================================


class TestDynamicOptions:
    """Test dynamic field options loading with pagination support."""

    @pytest.mark.asyncio
    async def test_load_folder_options(self, mock_httpx_response):
        """Test loading folder options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "folder1",
                        "name": "Folder 1",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    {
                        "id": "folder2",
                        "name": "Folder 2",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleDriveNode.load_field_options(
                "folder_id", credential_data, None
            )

            assert isinstance(result, dict)
            assert "options" in result
            assert "next_page_token" in result
            options = result["options"]
            # First option should be My Drive
            assert options[0]["label"] == "My Drive"
            assert options[0]["metadata"]["icon"] == "/icons/drive.svg"
            assert len(options) >= 1

    @pytest.mark.asyncio
    async def test_load_file_options(self, mock_httpx_response):
        """Test loading file options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {"id": "file1", "name": "File 1.txt", "mimeType": "text/plain"},
                    {
                        "id": "file2",
                        "name": "File 2.pdf",
                        "mimeType": "application/pdf",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleDriveNode.load_field_options(
                "file_id", credential_data, None
            )

            assert isinstance(result, dict)
            assert "options" in result
            assert "next_page_token" in result
            options = result["options"]
            for option in options:
                assert "value" in option
                assert "label" in option
                assert "metadata" in option

    @pytest.mark.asyncio
    async def test_watch_target_options_include_files_and_folders(self, mock_httpx_response):
        """File triggers should offer one combined file/folder picker."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        list_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "folder1",
                        "name": "Client Assets",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["parent1"],
                    },
                    {
                        "id": "file1",
                        "name": "Quarterly Report",
                        "mimeType": "text/plain",
                        "parents": ["parent1"],
                    },
                ]
            },
        )
        parent_response = mock_httpx_response(
            200,
            {"id": "parent1", "name": "Project Alpha"},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(side_effect=[list_response, parent_response])
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await GoogleDriveNode.load_field_options(
                "watch_target_id", credential_data, None
            )

            assert any(option["label"] == "Project Alpha  /  Client Assets" for option in result["options"])
            assert any(option["label"] == "Project Alpha  /  Quarterly Report" for option in result["options"])
            folder_option = next(option for option in result["options"] if option["value"] == "folder1")
            file_option = next(option for option in result["options"] if option["value"] == "file1")
            assert folder_option["metadata"]["icon"] == "/icons/drive.svg"
            assert file_option["metadata"]["icon"] is None
            assert file_option["metadata"]["emoji"] == "📄"

    @pytest.mark.asyncio
    async def test_watch_target_search_includes_my_drive(self, mock_httpx_response):
        """Searching for My Drive should still surface the synthetic root option in the mixed picker."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        list_response = mock_httpx_response(200, {"files": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=list_response
            )

            result = await GoogleDriveNode.load_field_options(
                "watch_target_id", credential_data, None, search="My Drive"
            )

            assert result["options"][0]["label"] == "My Drive"
            assert result["options"][0]["metadata"]["icon"] == "/icons/drive.svg"

    @pytest.mark.asyncio
    async def test_folder_and_file_options_show_parent_context(self, mock_httpx_response):
        """Nested items should show parent context so duplicate names are less ambiguous."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        folder_list_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "folder-child",
                        "name": "Specs",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["folder-parent"],
                    },
                ]
            },
        )
        file_list_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "file-child",
                        "name": "README.md",
                        "mimeType": "text/markdown",
                        "parents": ["folder-parent"],
                    },
                ]
            },
        )
        parent_response = mock_httpx_response(
            200,
            {"id": "folder-parent", "name": "Project Alpha"},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(
                side_effect=[
                    folder_list_response,
                    parent_response,
                    file_list_response,
                    parent_response,
                ]
            )
            mock_client.return_value.__aenter__.return_value.get = mock_get

            folder_result = await GoogleDriveNode.load_field_options(
                "folder_id", credential_data, None
            )
            file_result = await GoogleDriveNode.load_field_options(
                "file_id", credential_data, None
            )

            assert any(option["label"] == "Project Alpha  /  Specs" for option in folder_result["options"])
            assert any(option["label"] == "Project Alpha  /  README.md" for option in file_result["options"])
            file_option = next(option for option in file_result["options"] if option["value"] == "file-child")
            assert file_option["metadata"]["icon"] is None
            assert file_option["metadata"]["emoji"] == "📄"

    @pytest.mark.asyncio
    async def test_google_native_file_keeps_google_svg_icon(self, mock_httpx_response):
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        list_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "gdoc-1",
                        "name": "Planning Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=list_response
            )

            result = await GoogleDriveNode.load_field_options(
                "file_id", credential_data, None
            )

            option = result["options"][0]
            assert option["metadata"]["icon"] == "/icons/google-docs.svg"
            assert option["metadata"]["emoji"] == "📄"

    @pytest.mark.asyncio
    async def test_pagination_with_next_page_token(self, mock_httpx_response):
        """Test that pagination token is returned when more results are available."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        # Response with nextPageToken indicating more results
        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {"id": "file1", "name": "File 1.txt", "mimeType": "text/plain"}
                ],
                "nextPageToken": "next_page_abc123",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleDriveNode.load_field_options(
                "file_id", credential_data, None
            )

            assert result["next_page_token"] == "next_page_abc123"
            assert len(result["options"]) == 1

    @pytest.mark.asyncio
    async def test_load_next_page_with_token(self, mock_httpx_response):
        """Test loading subsequent page using page_token."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        # Second page response (no root folder option expected)
        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {
                        "id": "folder3",
                        "name": "Folder 3",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await GoogleDriveNode.load_field_options(
                "folder_id", credential_data, None, page_token="page_token_123"
            )

            # Verify page_token was passed to API
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            assert "params" in call_kwargs.kwargs or len(call_kwargs.args) > 1
            params = call_kwargs.kwargs.get(
                "params", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
            )
            assert params.get("pageToken") == "page_token_123"

            # On subsequent pages, no Root option should be included
            options = result["options"]
            assert len(options) == 1
            assert options[0]["label"] == "Folder 3"
            assert options[0]["metadata"]["icon"] == "/icons/drive.svg"


class TestDriveTriggerRuntime:
    def test_zero_change_trigger_output_does_not_propagate(self):
        assert (
            GoogleDriveNode.should_propagate_output(
                {"changes": [], "change_count": 0},
                {"operation": "on_file_changed"},
            )
            is False
        )
        assert (
            GoogleDriveNode.should_propagate_output(
                {"changes": [{"fileId": "f1"}], "change_count": 1},
                {"operation": "on_file_changed"},
            )
            is True
        )

    # Channel-keyed wake-up dedup is covered by the pure-mock unit suite at
    # tests/test_google_trigger_dedup_unit.py (runs in backend-tests.yml; no
    # credentials/DB), so it isn't duplicated in this integration file.


# ============================================================================
# Schema Generation Tests
# ============================================================================


class TestSchemaGeneration:
    """Test JSON schema generation."""

    def test_config_schema_generated(self):
        """Test that config schema is properly generated."""
        schema = GoogleDriveNode.get_config_schema()

        assert schema is not None
        assert "properties" in schema or "$defs" in schema

    def test_config_model_defined(self):
        """Test that config model is defined."""
        model = GoogleDriveNode.get_config_model()

        assert model is not None
        assert model == GoogleDriveNodeConfig


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
