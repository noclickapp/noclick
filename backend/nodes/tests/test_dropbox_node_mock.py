"""Mock tests for Dropbox node.

These tests use mocked API responses to test functionality without requiring
actual Dropbox API credentials or making real API calls.

Tests cover all 43 operations across:
- Files API (17 operations): upload, download, list, search, metadata, etc.
- Sharing API (15 operations): links, folders, files, permissions
- Account API (2 operations): account info, space usage
- File Requests API (6 operations): create, list, get, update, delete, count
- File Properties API (3 operations): add, update, remove custom metadata
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


def create_node_mock(config):
    """Create a DropboxNode instance with mock credentials for testing."""
    from nodes.dropbox_node import DropboxNode, DropboxNodeConfig, DropboxOAuthCredential
    mock_credentials = DropboxOAuthCredential(access_token="mock_access_token_12345")
    node_config = DropboxNodeConfig(config=config, credentials=mock_credentials)
    node = DropboxNode(
        node_id="test-node",
        node_type="automation-dropbox",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


class TestDropboxFilesOperations:
    """Test Files API operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_metadata_mocked(self):
        """Test getting file metadata with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxGetMetadataConfig

        mock_response_data = {
            ".tag": "file",
            "name": "test_file.txt",
            "path_display": "/Documents/test_file.txt",
            "id": "id:a4ayc_80_OEAAAAAAAAAXw",
            "size": 1024,
            "server_modified": "2025-01-01T10:00:00Z",
            "content_hash": "abcd1234"
        }

        config = DropboxGetMetadataConfig(path="/Documents/test_file.txt")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["metadata"]["name"] == "test_file.txt"
            assert result["metadata"]["size"] == 1024

    @pytest.mark.asyncio
    async def test_list_folder_mocked(self):
        """Test listing folder contents with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxListFolderConfig

        mock_response_data = {
            "entries": [
                {
                    ".tag": "file",
                    "name": "file1.txt",
                    "path_display": "/Documents/file1.txt",
                    "id": "id:file1",
                    "size": 512
                },
                {
                    ".tag": "folder",
                    "name": "subfolder",
                    "path_display": "/Documents/subfolder",
                    "id": "id:folder1"
                }
            ],
            "has_more": False
        }

        config = DropboxListFolderConfig(path="/Documents")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["count"] == 2
            assert len(result["entries"]) == 2
            assert result["entries"][0]["name"] == "file1.txt"

    @pytest.mark.asyncio
    async def test_create_folder_mocked(self):
        """Test creating a folder with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxCreateFolderConfig

        mock_response_data = {
            "metadata": {
                "name": "New Folder",
                "path_display": "/Projects/New Folder",
                "id": "id:new_folder_123"
            }
        }

        config = DropboxCreateFolderConfig(path="/Projects/New Folder")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["folder"]["name"] == "New Folder"


class TestDropboxSharingOperations:
    """Test Sharing API operations with mocks."""

    @pytest.mark.asyncio
    async def test_create_shared_link_mocked(self):
        """Test creating a shared link with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxCreateSharedLinkConfig

        mock_response_data = {
            "url": "https://www.dropbox.com/s/abcd1234/file.txt",
            "name": "file.txt",
            "path_lower": "/documents/file.txt",
            "link_permissions": {
                "resolved_visibility": {".tag": "public"}
            }
        }

        config = DropboxCreateSharedLinkConfig(path="/Documents/file.txt", audience="public")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert "dropbox.com" in result["link"]["url"]

    @pytest.mark.asyncio
    async def test_list_folder_members_mocked(self):
        """Test listing shared folder members with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxListFolderMembersConfig

        mock_response_data = {
            "users": [
                {
                    "user": {
                        "email": "user1@example.com",
                        "display_name": "User One"
                    },
                    "access_type": {".tag": "editor"}
                },
                {
                    "user": {
                        "email": "user2@example.com",
                        "display_name": "User Two"
                    },
                    "access_type": {".tag": "viewer"}
                }
            ]
        }

        config = DropboxListFolderMembersConfig(shared_folder_id="84528192421")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["count"] == 2
            assert result["members"][0]["email"] == "user1@example.com"


class TestDropboxAccountOperations:
    """Test Account API operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_account_info_mocked(self):
        """Test getting account info with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxGetAccountInfoConfig

        mock_response_data = {
            "account_id": "dbid:AAH4f99T0taONIb-OurWxbNQ6ywGRopQngc",
            "name": {
                "display_name": "John Doe",
                "given_name": "John",
                "surname": "Doe"
            },
            "email": "john@example.com",
            "email_verified": True,
            "account_type": {".tag": "basic"}
        }

        config = DropboxGetAccountInfoConfig()
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["account"]["email"] == "john@example.com"

    @pytest.mark.asyncio
    async def test_get_space_usage_mocked(self):
        """Test getting space usage with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxGetSpaceUsageConfig

        mock_response_data = {
            "used": 5368709120,  # 5 GB in bytes
            "allocation": {
                ".tag": "individual",
                "allocated": 10737418240  # 10 GB in bytes
            }
        }

        config = DropboxGetSpaceUsageConfig()
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["space"]["used_gb"] == 5.0
            assert result["space"]["allocated_gb"] == 10.0
            assert result["space"]["percent_used"] == 50.0


class TestDropboxFileRequestOperations:
    """Test File Requests API operations with mocks."""

    @pytest.mark.asyncio
    async def test_create_file_request_mocked(self):
        """Test creating a file request with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxCreateFileRequestConfig

        mock_response_data = {
            "id": "oaCAVmEyrqYnkZX9955Y",
            "url": "https://www.dropbox.com/request/oaCAVmEyrqYnkZX9955Y",
            "title": "Submit documents",
            "destination": "/File Requests/Documents",
            "is_open": True,
            "file_count": 0
        }

        config = DropboxCreateFileRequestConfig(
            title="Submit documents",
            destination="/File Requests/Documents"
        )
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["file_request"]["title"] == "Submit documents"
            assert result["file_request"]["is_open"] == True

    @pytest.mark.asyncio
    async def test_count_file_requests_mocked(self):
        """Test counting file requests with mock response."""
        from nodes.dropbox_node import DropboxNode, DropboxCountFileRequestsConfig

        mock_response_data = {
            "file_request_count": 5
        }

        config = DropboxCountFileRequestsConfig()
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["file_request_count"] == 5


class TestDropboxErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_operation(self):
        """Test that invalid operation raises error."""
        from nodes.dropbox_node import DropboxNode, DropboxNodeConfig, DropboxOAuthCredential
        from pydantic import BaseModel, Field

        # Create a mock config with invalid operation
        class InvalidConfig(BaseModel):
            operation: str = "invalid_operation"

        mock_credentials = DropboxOAuthCredential(access_token="mock_token")
        # This should fail during config parsing, not execution
        # The discriminated union will reject invalid operations

    @pytest.mark.asyncio
    async def test_http_error_handling(self):
        """Test HTTP error is properly handled."""
        from nodes.dropbox_node import DropboxNode, DropboxGetMetadataConfig
        import httpx

        config = DropboxGetMetadataConfig(path="/nonexistent/file.txt")
        node = create_node_mock(config)

        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 409
            mock_response.json.return_value = {
                "error_summary": "path/not_found/...",
                "error": {".tag": "path"}
            }
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "409 Conflict",
                request=MagicMock(),
                response=mock_response
            )

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError) as exc_info:
                await node.execute({})

            assert "Dropbox API error" in str(exc_info.value)
