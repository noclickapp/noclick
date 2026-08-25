"""Mock tests for OneDrive node - comprehensive coverage of all 37 operations."""

import json
import pytest
import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from dotenv import load_dotenv
from utils.ssrf import SSRFError

def create_node_mock(config):
    """Create an OneDriveNode instance with mock credentials for testing."""
    from nodes.onedrive_node import OneDriveNode, OneDriveNodeConfig, OneDriveOAuthCredential

    mock_credentials = OneDriveOAuthCredential(
        access_token="mock_access_token_12345",
        refresh_token="mock_refresh_token_67890",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com"
    )

    node_config = OneDriveNodeConfig(config=config, credentials=mock_credentials)
    return OneDriveNode(
        node_id="test-onedrive-node",
        node_type="automation-onedrive",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )

class TestOneDriveComprehensive:
    """Comprehensive tests for all 37 OneDrive operations."""

    # ========================================================================
    # Core File Operations (10 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_item_by_id(self):
        from nodes.onedrive_node import OneDriveGetItemConfig
        config = OneDriveGetItemConfig(action="get_item_metadata", item_id="01ABCDEF")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "01ABCDEF",
                "name": "document.pdf",
                "size": 1024,
                "createdDateTime": "2024-01-01T00:00:00Z",
                "lastModifiedDateTime": "2024-01-02T00:00:00Z",
                "file": {"mimeType": "application/pdf"},
                "webUrl": "https://onedrive.live.com/...",
                "@microsoft.graph.downloadUrl": "https://download.url",
                "parentReference": {"id": "parent123"}
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["id"] == "01ABCDEF"
            assert result["data"]["name"] == "document.pdf"

    @pytest.mark.asyncio
    async def test_get_item_by_path(self):
        from nodes.onedrive_node import OneDriveGetItemConfig
        config = OneDriveGetItemConfig(action="get_item_metadata", item_path="/Documents/file.txt")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "02XYZ",
                "name": "file.txt",
                "size": 512,
                "file": {"mimeType": "text/plain"}
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_children(self):
        from nodes.onedrive_node import OneDriveListChildrenConfig
        config = OneDriveListChildrenConfig(action="list_folder_contents", folder_id="folder123", top=50)
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {"id": "file1", "name": "doc1.pdf", "file": {"mimeType": "application/pdf"}},
                    {"id": "folder1", "name": "SubFolder", "folder": {}}
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_upload(self):
        from nodes.onedrive_node import OneDriveUploadConfig
        config = OneDriveUploadConfig(
            action="upload_file",
            file_name="test.txt",
            file_content="Hello World",
            content_type="text/plain"
        )
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "uploaded123",
                "name": "test.txt",
                "size": 11,
                "webUrl": "https://onedrive.live.com/...",
                "@microsoft.graph.downloadUrl": "https://download.url"
            }
            mock_response.status_code = 201
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["name"] == "test.txt"

    @pytest.mark.asyncio
    async def test_upload_session(self):
        from nodes.onedrive_node import OneDriveUploadSessionConfig
        config = OneDriveUploadSessionConfig(action="create_large_file_upload_session", file_name="large_file.zip")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "uploadUrl": "https://upload.session.url",
                "expirationDateTime": "2024-12-31T23:59:59Z",
                "nextExpectedRanges": ["0-"]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert "upload_url" in result["data"]

    @pytest.mark.asyncio
    async def test_download(self):
        from nodes.onedrive_node import OneDriveDownloadConfig
        config = OneDriveDownloadConfig(action="download_item", item_id="file123")
        node = create_node_mock(config)
        node.user_id = "test-user"
        with patch('httpx.AsyncClient') as mock_client, \
             patch('nodes.core.binary_output.create_resource_from_bytes', new_callable=AsyncMock) as mock_store:
            mock_response = MagicMock()
            mock_response.content = b"File content here"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            mock_store.return_value = {
                "download_url": "https://r2.example/onedrive-content.txt",
                "mime_type": "text/plain",
                "name": "file123",
                "size_bytes": len(b"File content here"),
            }
            result = await node.run({})
            assert result["status"] == "success"
            content = result["data"]["content"]
            assert content["url"] == "https://r2.example/onedrive-content.txt"
            assert content["mime_type"] == "text/plain"
            assert content["size_bytes"] == len(b"File content here")
            # resolver stored the raw bytes, not a base64 string
            assert mock_store.call_args.kwargs["body"] == b"File content here"
            assert mock_store.call_args.kwargs["content_type"] == "text/plain"
            # The download follows provider redirects through the shared SSRF
            # hook, not a plain client that could reach a private destination.
            assert mock_client.call_args.kwargs["event_hooks"]["request"]

    @pytest.mark.asyncio
    async def test_update_item(self):
        from nodes.onedrive_node import OneDriveUpdateItemConfig
        config = OneDriveUpdateItemConfig(action="update_item_metadata", item_id="item123", new_name="renamed.pdf")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "item123",
                "name": "renamed.pdf",
                "lastModifiedDateTime": "2024-01-03T00:00:00Z"
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["name"] == "renamed.pdf"

    @pytest.mark.asyncio
    async def test_create_folder(self):
        from nodes.onedrive_node import OneDriveCreateFolderConfig
        config = OneDriveCreateFolderConfig(action="create_folder", folder_name="New Folder")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "newfolder123",
                "name": "New Folder",
                "webUrl": "https://onedrive.live.com/...",
                "createdDateTime": "2024-01-01T00:00:00Z"
            }
            mock_response.status_code = 201
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["name"] == "New Folder"

    @pytest.mark.asyncio
    async def test_copy(self):
        from nodes.onedrive_node import OneDriveCopyConfig
        config = OneDriveCopyConfig(action="copy_item", item_id="item123", destination_folder_id="dest456")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.headers = {"Location": "https://monitor.url"}
            mock_response.status_code = 202
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert "monitor_url" in result["data"]

    @pytest.mark.asyncio
    async def test_move(self):
        from nodes.onedrive_node import OneDriveMoveConfig
        config = OneDriveMoveConfig(action="move_item", item_id="item123", destination_folder_id="dest456")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "item123",
                "name": "moved_file.pdf",
                "parentReference": {"id": "dest456"},
                "webUrl": "https://onedrive.live.com/..."
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete(self):
        from nodes.onedrive_node import OneDriveDeleteConfig
        config = OneDriveDeleteConfig(action="delete", item_id="item123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # File Management (3 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_restore(self):
        from nodes.onedrive_node import OneDriveRestoreConfig
        config = OneDriveRestoreConfig(action="restore_item_from_recycle_bin", item_id="deleted123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "deleted123",
                "name": "restored_file.pdf",
                "webUrl": "https://onedrive.live.com/..."
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_permanently_delete(self):
        from nodes.onedrive_node import OneDrivePermanentlyDeleteConfig
        config = OneDrivePermanentlyDeleteConfig(action="permanently_delete_item", item_id="item123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_drive(self):
        from nodes.onedrive_node import OneDriveGetDriveConfig
        config = OneDriveGetDriveConfig(action="get_drive_info")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "drive123",
                "driveType": "personal",
                "owner": {"user": {"displayName": "Test User"}},
                "quota": {
                    "total": 1099511627776,
                    "used": 536870912,
                    "remaining": 1099474756864,
                    "state": "normal"
                }
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert "quota" in result["data"]

    # ========================================================================
    # Search & Discovery (2 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_search(self):
        from nodes.onedrive_node import OneDriveSearchConfig
        config = OneDriveSearchConfig(action="search", query="report", top=10)
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {
                        "id": "result1",
                        "name": "quarterly_report.pdf",
                        "file": {},
                        "parentReference": {"path": "/drive/root:/Documents"},
                        "webUrl": "https://onedrive.live.com/...",
                        "size": 2048,
                        "lastModifiedDateTime": "2024-01-01T00:00:00Z"
                    }
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_delta(self):
        from nodes.onedrive_node import OneDriveDeltaConfig
        config = OneDriveDeltaConfig(action="track_drive_changes")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {"id": "change1", "name": "new_file.pdf", "file": {}, "lastModifiedDateTime": "2024-01-01T00:00:00Z"},
                    {"id": "change2", "name": "deleted_file.pdf", "deleted": {}}
                ],
                "@odata.deltaLink": "https://delta.link"
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert len(result["data"]["changes"]) == 2

    @pytest.mark.asyncio
    async def test_delta_token_cannot_exfiltrate_bearer(self):
        from nodes.onedrive_node import OneDriveDeltaConfig

        config = OneDriveDeltaConfig(
            action="track_drive_changes",
            delta_token="https://evil.example/steal",
        )
        node = create_node_mock(config)
        with patch("httpx.AsyncClient") as mock_client:
            with pytest.raises(SSRFError, match="outside"):
                await node.execute({})
        mock_client.return_value.__aenter__.return_value.get.assert_not_called()

    # ========================================================================
    # Sharing & Permissions (6 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_create_link(self):
        from nodes.onedrive_node import OneDriveCreateLinkConfig
        config = OneDriveCreateLinkConfig(action="create_sharing_link", item_id="item123", link_type="view", scope="anonymous")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "perm123",
                "link": {
                    "webUrl": "https://share.link",
                    "type": "view",
                    "scope": "anonymous"
                }
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert "link_url" in result["data"]

    @pytest.mark.asyncio
    async def test_list_permissions(self):
        from nodes.onedrive_node import OneDriveListPermissionsConfig
        config = OneDriveListPermissionsConfig(action="list_item_permissions", item_id="item123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {"id": "perm1", "roles": ["read"], "link": {"type": "view"}},
                    {"id": "perm2", "roles": ["write"], "grantedTo": {"user": {"email": "user@example.com"}}}
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_add_permission(self):
        from nodes.onedrive_node import OneDriveAddPermissionConfig
        config = OneDriveAddPermissionConfig(
            action="grant_item_permission",
            item_id="item123",
            recipient_email="user@example.com",
            role="read",
            send_invitation=True
        )
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [{"id": "perm123", "roles": ["read"]}]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_permission(self):
        from nodes.onedrive_node import OneDriveUpdatePermissionConfig
        config = OneDriveUpdatePermissionConfig(
            action="update_item_permission",
            item_id="item123",
            permission_id="perm456",
            new_role="write"
        )
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "perm456",
                "roles": ["write"]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_permission(self):
        from nodes.onedrive_node import OneDriveDeletePermissionConfig
        config = OneDriveDeletePermissionConfig(action="delete_item_permission", item_id="item123", permission_id="perm456")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_send_invite(self):
        from nodes.onedrive_node import OneDriveSendInviteConfig
        config = OneDriveSendInviteConfig(
            action="send_sharing_invitation",
            item_id="item123",
            recipient_email="user@example.com",
            message="Please review this file",
            require_sign_in=True
        )
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [{"id": "perm789"}]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # Versions (3 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_list_versions(self):
        from nodes.onedrive_node import OneDriveListVersionsConfig
        config = OneDriveListVersionsConfig(action="list_file_versions", item_id="file123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {"id": "v1", "lastModifiedDateTime": "2024-01-01T00:00:00Z", "size": 1024},
                    {"id": "v2", "lastModifiedDateTime": "2024-01-02T00:00:00Z", "size": 2048}
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_get_version(self):
        from nodes.onedrive_node import OneDriveGetVersionConfig
        config = OneDriveGetVersionConfig(action="get_version", item_id="file123", version_id="v1")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "v1",
                "lastModifiedDateTime": "2024-01-01T00:00:00Z",
                "size": 1024
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_restore_version(self):
        from nodes.onedrive_node import OneDriveRestoreVersionConfig
        config = OneDriveRestoreVersionConfig(action="restore_file_version", item_id="file123", version_id="v1")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # Thumbnails (2 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_list_thumbnails(self):
        from nodes.onedrive_node import OneDriveListThumbnailsConfig
        config = OneDriveListThumbnailsConfig(action="list_item_thumbnails", item_id="image123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [{
                    "id": "thumb1",
                    "small": {"url": "https://small.url"},
                    "medium": {"url": "https://medium.url"},
                    "large": {"url": "https://large.url"}
                }]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_thumbnail(self):
        from nodes.onedrive_node import OneDriveGetThumbnailConfig
        config = OneDriveGetThumbnailConfig(action="get_item_thumbnail", item_id="image123", size="medium")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "url": "https://thumbnail.url",
                "width": 176,
                "height": 176
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # Advanced Features (6 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_preview(self):
        from nodes.onedrive_node import OneDrivePreviewConfig
        config = OneDrivePreviewConfig(action="preview", item_id="doc123", viewer="office")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "getUrl": "https://preview.url",
                "postUrl": "https://post.url",
                "postParameters": {}
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_content_stream(self):
        from nodes.onedrive_node import OneDriveGetContentStreamConfig
        config = OneDriveGetContentStreamConfig(action="get_item_download_stream", item_id="file123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "@microsoft.graph.downloadUrl": "https://download.stream.url"
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_check_out(self):
        from nodes.onedrive_node import OneDriveCheckOutConfig
        config = OneDriveCheckOutConfig(action="check_out_file", item_id="doc123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_check_in(self):
        from nodes.onedrive_node import OneDriveCheckInConfig
        config = OneDriveCheckInConfig(action="check_in_file", item_id="doc123", comment="Updated content")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_discard_checkout(self):
        from nodes.onedrive_node import OneDriveDiscardCheckoutConfig
        config = OneDriveDiscardCheckoutConfig(action="discard_file_checkout", item_id="doc123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_analytics(self):
        from nodes.onedrive_node import OneDriveGetAnalyticsConfig
        config = OneDriveGetAnalyticsConfig(action="get_item_analytics", item_id="file123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "itemActivityStats": [],
                "allTime": {"access": {"actionCount": 100}},
                "lastSevenDays": {"access": {"actionCount": 10}}
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # Special Items (5 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_special_folder(self):
        from nodes.onedrive_node import OneDriveGetSpecialFolderConfig
        config = OneDriveGetSpecialFolderConfig(action="get_special_folder", folder_name="documents")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "docs123",
                "name": "Documents",
                "webUrl": "https://onedrive.live.com/..."
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_shared_with_me(self):
        from nodes.onedrive_node import OneDriveListSharedWithMeConfig
        config = OneDriveListSharedWithMeConfig(action="list_shared_items", top=20)
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {
                        "id": "shared1",
                        "name": "Shared Document.pdf",
                        "file": {},
                        "remoteItem": {"shared": {"sharedBy": {"user": {"displayName": "John Doe"}}}},
                        "webUrl": "https://onedrive.live.com/..."
                    }
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_recent(self):
        from nodes.onedrive_node import OneDriveListRecentConfig
        config = OneDriveListRecentConfig(action="list_recent_items", top=10)
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "value": [
                    {
                        "id": "recent1",
                        "name": "Recent File.docx",
                        "file": {},
                        "lastModifiedDateTime": "2024-01-03T00:00:00Z",
                        "webUrl": "https://onedrive.live.com/..."
                    }
                ]
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_follow(self):
        from nodes.onedrive_node import OneDriveFollowConfig
        config = OneDriveFollowConfig(action="follow_item", item_id="item123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": "item123",
                "name": "Followed Document.pdf",
                "following": True
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unfollow(self):
        from nodes.onedrive_node import OneDriveUnfollowConfig
        config = OneDriveUnfollowConfig(action="unfollow_item", item_id="item123")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "success"

    # ========================================================================
    # Error Handling (2 tests)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        from nodes.onedrive_node import OneDriveGetItemConfig, OneDriveNode, OneDriveNodeConfig
        config = OneDriveGetItemConfig(action="get_item_metadata", item_id="item123")
        node_config = OneDriveNodeConfig(config=config, credentials=None)
        node = OneDriveNode(
            node_id="test-node",
            node_type="automation-onedrive",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )
        with pytest.raises(ValueError, match="OneDrive credentials required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error_404(self):
        from nodes.onedrive_node import OneDriveGetItemConfig
        config = OneDriveGetItemConfig(action="get_item_metadata", item_id="nonexistent")
        node = create_node_mock(config)
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Item not found"
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            result = await node.execute({})
            assert result["status"] == "error"
            assert "404" in str(result.get("status_code", ""))
