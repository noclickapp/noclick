"""
Mock tests for the Google Cloud Storage (JSON API v1) node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Buckets: list, get, create, update, patch, delete, lock retention policy
- IAM: get policy, set policy, test permissions
- Objects: list, get, download, upload, update, patch, delete, copy, rewrite,
  compose, move, restore, get ACL
- Notifications: create, list, delete
- Projects: create HMAC key, list HMAC keys, get service account
- Error handling: API errors, missing credentials
- Dynamic options: bucket dropdown
"""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.core.media_resolver import ResolvedMedia
from nodes.google_cloud_storage_node import (
    GoogleCloudStorageNode,
    GoogleCloudStorageNodeConfig,
    GoogleCloudStorageOAuthCredential,
    GoogleCloudStorageServiceAccountCredential,
    GCSListBucketsConfig,
    GCSGetBucketConfig,
    GCSCreateBucketConfig,
    GCSUpdateBucketConfig,
    GCSPatchBucketConfig,
    GCSDeleteBucketConfig,
    GCSLockRetentionPolicyConfig,
    GCSGetStorageLayoutConfig,
    GCSRestoreBucketConfig,
    GCSRelocateBucketConfig,
    GCSGetBucketIamConfig,
    GCSSetBucketIamConfig,
    GCSTestIamPermissionsConfig,
    GCSGetObjectIamConfig,
    GCSSetObjectIamConfig,
    GCSTestObjectIamPermissionsConfig,
    GCSListObjectsConfig,
    GCSGetObjectConfig,
    GCSDownloadObjectConfig,
    GCSUploadObjectConfig,
    GCSUpdateObjectConfig,
    GCSPatchObjectConfig,
    GCSDeleteObjectConfig,
    GCSCopyObjectConfig,
    GCSRewriteObjectConfig,
    GCSComposeObjectsConfig,
    GCSMoveObjectConfig,
    GCSRestoreObjectConfig,
    GCSGetObjectAclConfig,
    GCSBulkRestoreObjectsConfig,
    GCSCreateNotificationConfig,
    GCSGetNotificationConfig,
    GCSListNotificationsConfig,
    GCSDeleteNotificationConfig,
    GCSCreateHmacKeyConfig,
    GCSListHmacKeysConfig,
    GCSGetHmacKeyConfig,
    GCSUpdateHmacKeyConfig,
    GCSDeleteHmacKeyConfig,
    GCSGetServiceAccountConfig,
    GCSGetOperationConfig,
    GCSListOperationsConfig,
    GCSCancelOperationConfig,
    GCSAdvanceRelocateBucketConfig,
    GCSListBucketAclConfig,
    GCSGetBucketAclConfig,
    GCSCreateBucketAclConfig,
    GCSPatchBucketAclConfig,
    GCSUpdateBucketAclConfig,
    GCSDeleteBucketAclConfig,
    GCSListDefaultObjectAclConfig,
    GCSGetDefaultObjectAclConfig,
    GCSCreateDefaultObjectAclConfig,
    GCSPatchDefaultObjectAclConfig,
    GCSUpdateDefaultObjectAclConfig,
    GCSDeleteDefaultObjectAclConfig,
    GCSListObjectAclEntriesConfig,
    GCSGetObjectAclEntryConfig,
    GCSCreateObjectAclEntryConfig,
    GCSPatchObjectAclEntryConfig,
    GCSUpdateObjectAclEntryConfig,
    GCSDeleteObjectAclEntryConfig,
    GCSListFoldersConfig,
    GCSGetFolderConfig,
    GCSCreateFolderConfig,
    GCSRenameFolderConfig,
    GCSDeleteFolderConfig,
    GCSDeleteFolderRecursiveConfig,
    GCSListManagedFoldersConfig,
    GCSGetManagedFolderConfig,
    GCSCreateManagedFolderConfig,
    GCSDeleteManagedFolderConfig,
    GCSGetManagedFolderIamConfig,
    GCSSetManagedFolderIamConfig,
    GCSTestManagedFolderIamPermissionsConfig,
    GCSListAnywhereCachesConfig,
    GCSGetAnywhereCacheConfig,
    GCSCreateAnywhereCacheConfig,
    GCSUpdateAnywhereCacheConfig,
    GCSDisableAnywhereCacheConfig,
    GCSPauseAnywhereCacheConfig,
    GCSResumeAnywhereCacheConfig,
    GCSGetProjectIntelligenceConfig,
    GCSUpdateProjectIntelligenceConfig,
    GCSGetFolderIntelligenceConfig,
    GCSUpdateFolderIntelligenceConfig,
    GCSGetOrganizationIntelligenceConfig,
    GCSUpdateOrganizationIntelligenceConfig,
    GCSOnNewObjectConfig,
)


@pytest.fixture
def oauth_credentials():
    return GoogleCloudStorageOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


@pytest.fixture
def service_account_credentials():
    return GoogleCloudStorageServiceAccountCredential(
        service_account_json=json.dumps(
            {
                "type": "service_account",
                "project_id": "proj-1",
                "private_key_id": "key-123",
                "private_key": "-----BEGIN PRIVATE KEY-----\nmock\n-----END PRIVATE KEY-----\n",
                "client_email": "svc@proj-1.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )


def create_node(config):
    node = GoogleCloudStorageNode(
        node_id="test-gcs-node",
        node_type="automation-google-cloud-storage",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )

    # Bypass the OAuth refresh DB round-trip; the token resolution itself is not
    # the subject under test in these per-operation mocks.
    async def _fake_token(_credentials):
        return "mock_access_token"

    node._ensure_fresh_token = _fake_token
    return node


def create_mock_response(status_code=200, json_data=None, text="", headers=None, content=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.headers = headers or {}
    if content is not None:
        mock_response.content = content
    else:
        mock_response.content = text.encode() if text else (b"" if json_data is None else b"{}")
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, text="", headers=None, content=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text, headers=headers, content=content)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


PATCH_TARGET = "nodes.google_cloud_storage_node.httpx.AsyncClient"


# ============================================================================
# Buckets
# ============================================================================


class TestGCSBucketsMock:
    @pytest.mark.asyncio
    async def test_list_buckets(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListBucketsConfig(project_id="proj-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"name": "bucket-a"}, {"name": "bucket-b"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_buckets"
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_buckets_with_service_account_credentials(self, service_account_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListBucketsConfig(project_id="proj-1"),
            credentials=service_account_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"name": "bucket-a"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_buckets"
        assert result["data"]["items"][0]["name"] == "bucket-a"

    @pytest.mark.asyncio
    async def test_get_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetBucketConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "bucket-a", "location": "US"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_bucket"
        assert result["data"]["name"] == "bucket-a"

    @pytest.mark.asyncio
    async def test_create_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCreateBucketConfig(
                project_id="proj-1", name="new-bucket", location="US", storage_class="STANDARD"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "new-bucket", "storageClass": "STANDARD"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_bucket"
        assert result["data"]["name"] == "new-bucket"

    @pytest.mark.asyncio
    async def test_update_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUpdateBucketConfig(
                bucket="bucket-a", metadata_json='{"labels": {"env": "prod"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "bucket-a", "labels": {"env": "prod"}})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_bucket"

    @pytest.mark.asyncio
    async def test_patch_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSPatchBucketConfig(
                bucket="bucket-a", metadata_json='{"labels": {"team": "data"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "bucket-a"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "patch_bucket"

    @pytest.mark.asyncio
    async def test_delete_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDeleteBucketConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_bucket"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_lock_retention_policy(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSLockRetentionPolicyConfig(bucket="bucket-a", metageneration="3"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "bucket-a", "metageneration": "3"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "lock_retention_policy"

    @pytest.mark.asyncio
    async def test_get_storage_layout(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetStorageLayoutConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"bucket": "bucket-a", "location": "us-central1"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_storage_layout"

    @pytest.mark.asyncio
    async def test_restore_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSRestoreBucketConfig(bucket="bucket-a", generation="123"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "bucket-a", "generation": "123"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "restore_bucket"

    @pytest.mark.asyncio
    async def test_relocate_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSRelocateBucketConfig(bucket="bucket-a", destination_location="US-EAST1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "operations/op-1", "done": False})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "relocate_bucket"


# ============================================================================
# IAM
# ============================================================================


class TestGCSIamMock:
    @pytest.mark.asyncio
    async def test_get_bucket_iam(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetBucketIamConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.admin"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_bucket_iam"

    @pytest.mark.asyncio
    async def test_set_bucket_iam(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSSetBucketIamConfig(
                bucket="bucket-a", policy_json='{"bindings": [{"role": "roles/storage.objectViewer"}]}'
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.objectViewer"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "set_bucket_iam"

    @pytest.mark.asyncio
    async def test_test_iam_permissions(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSTestIamPermissionsConfig(
                bucket="bucket-a", permissions="storage.buckets.get,storage.objects.list"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"permissions": ["storage.buckets.get"]})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["params"] = kwargs.get("params")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "test_iam_permissions"
        assert request_spy["method"] == "GET"
        assert request_spy["params"]["permissions"] == [
            "storage.buckets.get",
            "storage.objects.list",
        ]

    @pytest.mark.asyncio
    async def test_get_object_iam(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetObjectIamConfig(bucket="bucket-a", object_name="reports/q1.json"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.objectViewer"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_object_iam"

    @pytest.mark.asyncio
    async def test_set_object_iam(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSSetObjectIamConfig(
                bucket="bucket-a",
                object_name="reports/q1.json",
                policy_json='{"bindings":[{"role":"roles/storage.objectAdmin"}]}',
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.objectAdmin"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "set_object_iam"

    @pytest.mark.asyncio
    async def test_test_object_iam_permissions(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSTestObjectIamPermissionsConfig(
                bucket="bucket-a",
                object_name="reports/q1.json",
                permissions="storage.objects.get,storage.objects.update",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"permissions": ["storage.objects.get"]})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["params"] = kwargs.get("params")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "test_object_iam_permissions"
        assert request_spy["method"] == "GET"
        assert request_spy["params"]["permissions"] == [
            "storage.objects.get",
            "storage.objects.update",
        ]


# ============================================================================
# Objects
# ============================================================================


class TestGCSObjectsMock:
    @pytest.mark.asyncio
    async def test_list_objects(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListObjectsConfig(bucket="bucket-a", prefix="logs/"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"name": "logs/a.txt"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_objects"
        assert result["data"]["items"][0]["name"] == "logs/a.txt"

    @pytest.mark.asyncio
    async def test_get_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetObjectConfig(bucket="bucket-a", object_name="reports/q1.json"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "reports/q1.json", "size": "1024"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_object"
        assert result["data"]["name"] == "reports/q1.json"

    @pytest.mark.asyncio
    async def test_download_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDownloadObjectConfig(bucket="bucket-a", object_name="readme.txt"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, None, text="hello world")
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "download_object"
        assert result["data"]["content"] == "hello world"
        assert result["data"]["content_text"] == "hello world"
        assert result["data"]["content_base64"] == "aGVsbG8gd29ybGQ="

    @pytest.mark.asyncio
    async def test_upload_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUploadObjectConfig(
                bucket="bucket-a", object_name="out.txt", content="data", content_type="text/plain"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "out.txt", "bucket": "bucket-a"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_object"
        assert result["data"]["name"] == "out.txt"

    @pytest.mark.asyncio
    async def test_upload_object_from_media_input(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUploadObjectConfig(
                bucket="bucket-a",
                object_name="asset.bin",
                media_input="res-123",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "asset.bin", "bucket": "bucket-a"})

        async def fake_resolve(value, **kwargs):
            assert value == "res-123"
            return ResolvedMedia(b"\x00\x01\x02", "application/octet-stream", "asset.bin")

        with patch("nodes.core.media_resolver.resolve_media_input", fake_resolve), patch(
            PATCH_TARGET, return_value=mock_client
        ):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_object"
        assert result["data"]["name"] == "asset.bin"

    @pytest.mark.asyncio
    async def test_upload_object_resumable(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUploadObjectConfig(
                bucket="bucket-a",
                object_name="video.bin",
                content_base64="AQID",
                content_type="application/octet-stream",
                upload_type="resumable",
                metadata_json='{"metadata": {"source": "test"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        init_response = create_mock_response(200, None, headers={"Location": "https://upload-session"})
        upload_response = create_mock_response(200, {"name": "video.bin", "bucket": "bucket-a"})
        mock_client = Mock()
        call_count = {"count": 0}

        async def async_request(*args, **kwargs):
            call_count["count"] += 1
            return init_response if call_count["count"] == 1 else upload_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client), patch(
            "nodes.google_cloud_storage_node.assert_url_allowed",
            new_callable=AsyncMock,
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_object"
        assert result["data"]["name"] == "video.bin"

    @pytest.mark.asyncio
    async def test_upload_object_resumable_rejects_private_session_uri(
        self, oauth_credentials
    ):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUploadObjectConfig(
                bucket="bucket-a",
                object_name="video.bin",
                content_base64="AQID",
                content_type="application/octet-stream",
                upload_type="resumable",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        init_response = create_mock_response(
            200,
            None,
            headers={"Location": "http://169.254.169.254/latest/meta-data"},
        )
        mock_client = Mock()
        mock_client.request = AsyncMock(return_value=init_response)

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "error"
        assert "non-public address" in result["error"]
        assert mock_client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_update_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUpdateObjectConfig(
                bucket="bucket-a", object_name="out.txt", metadata_json='{"contentType": "text/csv"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "out.txt", "contentType": "text/csv"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_object"

    @pytest.mark.asyncio
    async def test_patch_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSPatchObjectConfig(
                bucket="bucket-a", object_name="out.txt", metadata_json='{"metadata": {"k": "v"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "out.txt"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "patch_object"

    @pytest.mark.asyncio
    async def test_delete_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDeleteObjectConfig(bucket="bucket-a", object_name="out.txt"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_object"

    @pytest.mark.asyncio
    async def test_copy_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCopyObjectConfig(
                source_bucket="src", source_object="a.txt",
                destination_bucket="dst", destination_object="b.txt",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "b.txt", "bucket": "dst"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "copy_object"
        assert result["data"]["name"] == "b.txt"

    @pytest.mark.asyncio
    async def test_rewrite_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSRewriteObjectConfig(
                source_bucket="src", source_object="big.bin",
                destination_bucket="dst", destination_object="big.bin",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"done": True, "resource": {"name": "big.bin"}})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "rewrite_object"

    @pytest.mark.asyncio
    async def test_compose_objects(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSComposeObjectsConfig(
                bucket="bucket-a", destination_object="merged.txt", source_objects="part1.txt,part2.txt"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "merged.txt"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "compose_objects"

    @pytest.mark.asyncio
    async def test_move_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSMoveObjectConfig(
                bucket="bucket-a", source_object="old.txt", destination_object="new.txt"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "new.txt"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "move_object"

    @pytest.mark.asyncio
    async def test_restore_object(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSRestoreObjectConfig(
                bucket="bucket-a", object_name="gone.txt", generation="1700000000000000"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "gone.txt"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "restore_object"

    @pytest.mark.asyncio
    async def test_get_object_acl(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetObjectAclConfig(bucket="bucket-a", object_name="out.txt"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"role": "OWNER"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_object_acl"

    @pytest.mark.asyncio
    async def test_bulk_restore_objects(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSBulkRestoreObjectsConfig(bucket="bucket-a", allow_overwrite=True),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "operations/bulk-1", "done": False})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "bulk_restore_objects"


# ============================================================================
# Notifications
# ============================================================================


class TestGCSNotificationsMock:
    @pytest.mark.asyncio
    async def test_create_notification(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCreateNotificationConfig(
                bucket="bucket-a",
                topic="//pubsub.googleapis.com/projects/proj-1/topics/events",
                event_types="OBJECT_FINALIZE,OBJECT_DELETE",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"id": "1", "topic": "events"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_notification"
        assert result["data"]["id"] == "1"

    @pytest.mark.asyncio
    async def test_list_notifications(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListNotificationsConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": "1"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_notifications"

    @pytest.mark.asyncio
    async def test_get_notification(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetNotificationConfig(bucket="bucket-a", notification_id="12"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"id": "12", "topic": "//pubsub.googleapis.com/projects/p/topics/t"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_notification"

    @pytest.mark.asyncio
    async def test_delete_notification(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDeleteNotificationConfig(bucket="bucket-a", notification_id="1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_notification"


# ============================================================================
# Projects
# ============================================================================


class TestGCSProjectsMock:
    @pytest.mark.asyncio
    async def test_create_hmac_key(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCreateHmacKeyConfig(
                project_id="proj-1", service_account_email="sa@proj-1.iam.gserviceaccount.com"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"secret": "abc", "metadata": {"accessId": "GOOG1"}})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_hmac_key"

    @pytest.mark.asyncio
    async def test_list_hmac_keys(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListHmacKeysConfig(project_id="proj-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"items": [{"accessId": "GOOG1"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_hmac_keys"

    @pytest.mark.asyncio
    async def test_get_hmac_key(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetHmacKeyConfig(project_id="proj-1", access_id="GOOG1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"accessId": "GOOG1", "state": "ACTIVE"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_hmac_key"

    @pytest.mark.asyncio
    async def test_update_hmac_key(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUpdateHmacKeyConfig(project_id="proj-1", access_id="GOOG1", state="INACTIVE"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"accessId": "GOOG1", "state": "INACTIVE"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_hmac_key"

    @pytest.mark.asyncio
    async def test_delete_hmac_key(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDeleteHmacKeyConfig(project_id="proj-1", access_id="GOOG1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_hmac_key"

    @pytest.mark.asyncio
    async def test_get_service_account(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetServiceAccountConfig(project_id="proj-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"email_address": "service@gs-project-accounts.iam.gserviceaccount.com"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_service_account"


# ============================================================================
# Operations
# ============================================================================


class TestGCSOperationsMock:
    @pytest.mark.asyncio
    async def test_get_operation(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetOperationConfig(bucket="bucket-a", operation_id="op-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "op-1", "done": False})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_operation"

    @pytest.mark.asyncio
    async def test_list_operations(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSListOperationsConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"operations": [{"name": "op-1"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_operations"

    @pytest.mark.asyncio
    async def test_cancel_operation(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCancelOperationConfig(bucket="bucket-a", operation_id="op-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "cancel_operation"

    @pytest.mark.asyncio
    async def test_advance_relocate_bucket(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSAdvanceRelocateBucketConfig(bucket="bucket-a", operation_id="op-1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"name": "op-1", "done": False})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "advance_relocate_bucket"


# ============================================================================
# Bucket / Object ACLs, Folders, Managed Folders, Anywhere Cache
# ============================================================================


class TestGCSAclAndFolderMock:
    @pytest.mark.asyncio
    async def test_list_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListBucketAclConfig(bucket="bucket-a"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"entity": "allUsers", "role": "READER"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_bucket_acl"

    @pytest.mark.asyncio
    async def test_get_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetBucketAclConfig(bucket="bucket-a", entity="allUsers"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_bucket_acl"

    @pytest.mark.asyncio
    async def test_create_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSCreateBucketAclConfig(bucket="bucket-a", entity="allUsers", role="READER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_bucket_acl"

    @pytest.mark.asyncio
    async def test_patch_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSPatchBucketAclConfig(bucket="bucket-a", entity="allUsers", role="OWNER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "patch_bucket_acl"

    @pytest.mark.asyncio
    async def test_update_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateBucketAclConfig(bucket="bucket-a", entity="allUsers", role="OWNER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_bucket_acl"

    @pytest.mark.asyncio
    async def test_delete_bucket_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDeleteBucketAclConfig(bucket="bucket-a", entity="allUsers"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_bucket_acl"

    @pytest.mark.asyncio
    async def test_list_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListDefaultObjectAclConfig(bucket="bucket-a"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"entity": "allUsers", "role": "READER"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_default_object_acl"

    @pytest.mark.asyncio
    async def test_get_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetDefaultObjectAclConfig(bucket="bucket-a", entity="allUsers"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_default_object_acl"

    @pytest.mark.asyncio
    async def test_create_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSCreateDefaultObjectAclConfig(bucket="bucket-a", entity="allUsers", role="READER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_default_object_acl"

    @pytest.mark.asyncio
    async def test_patch_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSPatchDefaultObjectAclConfig(bucket="bucket-a", entity="allUsers", role="OWNER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "patch_default_object_acl"

    @pytest.mark.asyncio
    async def test_update_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateDefaultObjectAclConfig(bucket="bucket-a", entity="allUsers", role="OWNER"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_default_object_acl"

    @pytest.mark.asyncio
    async def test_delete_default_object_acl(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDeleteDefaultObjectAclConfig(bucket="bucket-a", entity="allUsers"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_default_object_acl"

    @pytest.mark.asyncio
    async def test_list_object_acl_entries(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListObjectAclEntriesConfig(bucket="bucket-a", object_name="file.txt"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"entity": "allUsers", "role": "READER"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_object_acl_entries"

    @pytest.mark.asyncio
    async def test_get_object_acl_entry(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetObjectAclEntryConfig(
                    bucket="bucket-a", object_name="file.txt", entity="allUsers"
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_object_acl_entry"

    @pytest.mark.asyncio
    async def test_create_object_acl_entry(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSCreateObjectAclEntryConfig(
                    bucket="bucket-a", object_name="file.txt", entity="allUsers", role="READER"
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "READER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_object_acl_entry"

    @pytest.mark.asyncio
    async def test_patch_object_acl_entry(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSPatchObjectAclEntryConfig(
                    bucket="bucket-a", object_name="file.txt", entity="allUsers", role="OWNER"
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "patch_object_acl_entry"

    @pytest.mark.asyncio
    async def test_update_object_acl_entry(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateObjectAclEntryConfig(
                    bucket="bucket-a", object_name="file.txt", entity="allUsers", role="OWNER"
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"entity": "allUsers", "role": "OWNER"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_object_acl_entry"

    @pytest.mark.asyncio
    async def test_delete_object_acl_entry(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDeleteObjectAclEntryConfig(
                    bucket="bucket-a", object_name="file.txt", entity="allUsers"
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_object_acl_entry"

    @pytest.mark.asyncio
    async def test_list_folders(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListFoldersConfig(bucket="bucket-a", prefix="reports/"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"name": "reports/2026/"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_folders"

    @pytest.mark.asyncio
    async def test_get_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetFolderConfig(bucket="bucket-a", folder_name="reports/"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "reports/"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_folder"

    @pytest.mark.asyncio
    async def test_create_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSCreateFolderConfig(bucket="bucket-a", folder_name="reports/", recursive=True),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "reports/"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_folder"

    @pytest.mark.asyncio
    async def test_rename_folder(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSRenameFolderConfig(
                bucket="bucket-a",
                source_folder_name="reports/",
                destination_folder_name="archive/",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"name": "operations/folder-rename", "done": False})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["url"] = kwargs.get("url")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "rename_folder"
        assert request_spy["method"] == "POST"
        assert "/renameTo/folders/" in request_spy["url"]

    @pytest.mark.asyncio
    async def test_delete_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDeleteFolderConfig(bucket="bucket-a", folder_name="reports/"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_folder"

    @pytest.mark.asyncio
    async def test_delete_folder_recursive(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSDeleteFolderRecursiveConfig(
                bucket="bucket-a",
                folder_name="reports/",
                if_metageneration_match="7",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"name": "operations/folder-delete", "done": False})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["url"] = kwargs.get("url")
            request_spy["params"] = kwargs.get("params")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_folder_recursive"
        assert request_spy["method"] == "POST"
        assert request_spy["url"].endswith("/deleteRecursive")
        assert request_spy["params"]["ifMetagenerationMatch"] == "7"

    @pytest.mark.asyncio
    async def test_list_managed_folders(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListManagedFoldersConfig(bucket="bucket-a"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"name": "managed/root"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_managed_folders"

    @pytest.mark.asyncio
    async def test_get_managed_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetManagedFolderConfig(bucket="bucket-a", managed_folder="managed/root"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "managed/root"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_managed_folder"

    @pytest.mark.asyncio
    async def test_create_managed_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSCreateManagedFolderConfig(bucket="bucket-a", managed_folder="managed/root"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "managed/root"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_managed_folder"

    @pytest.mark.asyncio
    async def test_delete_managed_folder(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDeleteManagedFolderConfig(
                    bucket="bucket-a", managed_folder="managed/root", allow_non_empty=True
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(204, None)
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_managed_folder"

    @pytest.mark.asyncio
    async def test_get_managed_folder_iam(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetManagedFolderIamConfig(
                    bucket="bucket-a", managed_folder="managed/root", requested_policy_version=3
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.admin"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_managed_folder_iam"

    @pytest.mark.asyncio
    async def test_set_managed_folder_iam(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSSetManagedFolderIamConfig(
                    bucket="bucket-a",
                    managed_folder="managed/root",
                    policy_json='{"bindings": [{"role": "roles/storage.objectViewer"}]}',
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"bindings": [{"role": "roles/storage.objectViewer"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "set_managed_folder_iam"

    @pytest.mark.asyncio
    async def test_test_managed_folder_iam_permissions(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSTestManagedFolderIamPermissionsConfig(
                bucket="bucket-a",
                managed_folder="managed/root",
                permissions="storage.managedfolders.get,storage.managedfolders.list",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"permissions": ["storage.managedfolders.get"]})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["params"] = kwargs.get("params")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "test_managed_folder_iam_permissions"
        assert request_spy["method"] == "GET"
        assert request_spy["params"]["permissions"] == [
            "storage.managedfolders.get",
            "storage.managedfolders.list",
        ]

    @pytest.mark.asyncio
    async def test_list_anywhere_caches(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSListAnywhereCachesConfig(bucket="bucket-a"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"items": [{"zone": "us-east1-b", "state": "RUNNING"}]})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_anywhere_caches"

    @pytest.mark.asyncio
    async def test_get_anywhere_cache(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetAnywhereCacheConfig(bucket="bucket-a", anywhere_cache_id="us-east1-b"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"zone": "us-east1-b", "state": "RUNNING"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_anywhere_cache"

    @pytest.mark.asyncio
    async def test_create_anywhere_cache(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSCreateAnywhereCacheConfig(
                bucket="bucket-a", zone="us-east1-b", ttl="86400s", ingest_on_write=True
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"name": "operations/cache-create", "done": False})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["json"] = kwargs.get("json")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_anywhere_cache"
        assert request_spy["method"] == "POST"
        assert request_spy["json"]["zone"] == "us-east1-b"
        assert request_spy["json"]["ingestOnWrite"] is True

    @pytest.mark.asyncio
    async def test_update_anywhere_cache(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateAnywhereCacheConfig(
                    bucket="bucket-a",
                    anywhere_cache_id="us-east1-b",
                    ttl="70000s",
                    ingest_on_write=False,
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "operations/cache-update", "done": False})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_anywhere_cache"

    @pytest.mark.asyncio
    async def test_disable_anywhere_cache(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSDisableAnywhereCacheConfig(bucket="bucket-a", anywhere_cache_id="us-east1-b"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"zone": "us-east1-b", "state": "DISABLED"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "disable_anywhere_cache"

    @pytest.mark.asyncio
    async def test_pause_anywhere_cache(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSPauseAnywhereCacheConfig(bucket="bucket-a", anywhere_cache_id="us-east1-b"),
                credentials=oauth_credentials,
            )
        )
        request_spy = {}
        mock_response = create_mock_response(200, {"zone": "us-east1-b", "state": "PAUSED"})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["url"] = kwargs.get("url")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "pause_anywhere_cache"
        assert request_spy["method"] == "POST"
        assert request_spy["url"].endswith("/pause")

    @pytest.mark.asyncio
    async def test_resume_anywhere_cache(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSResumeAnywhereCacheConfig(bucket="bucket-a", anywhere_cache_id="us-east1-b"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"zone": "us-east1-b", "state": "RUNNING"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "resume_anywhere_cache"

    @pytest.mark.asyncio
    async def test_get_project_intelligence_config(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetProjectIntelligenceConfig(project_id="proj-1"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "projects/proj-1/locations/global/intelligenceConfig"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_project_intelligence_config"

    @pytest.mark.asyncio
    async def test_update_project_intelligence_config(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUpdateProjectIntelligenceConfig(
                project_id="proj-1",
                intelligence_config_json='{"editionConfig":"STANDARD"}',
                update_mask="editionConfig",
                request_id="req-1",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        request_spy = {}
        mock_response = create_mock_response(200, {"editionConfig": "STANDARD"})
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            request_spy["method"] = kwargs.get("method")
            request_spy["params"] = kwargs.get("params")
            request_spy["json"] = kwargs.get("json")
            return mock_response

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_project_intelligence_config"
        assert request_spy["method"] == "PATCH"
        assert request_spy["params"]["updateMask"] == "editionConfig"
        assert request_spy["json"]["editionConfig"] == "STANDARD"

    @pytest.mark.asyncio
    async def test_get_folder_intelligence_config(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetFolderIntelligenceConfig(folder_id="123456789"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "folders/123456789/locations/global/intelligenceConfig"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_folder_intelligence_config"

    @pytest.mark.asyncio
    async def test_update_folder_intelligence_config(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateFolderIntelligenceConfig(
                    folder_id="123456789",
                    intelligence_config_json='{"editionConfig":"DISABLED"}',
                    update_mask="editionConfig",
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"editionConfig": "DISABLED"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_folder_intelligence_config"

    @pytest.mark.asyncio
    async def test_get_organization_intelligence_config(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSGetOrganizationIntelligenceConfig(organization_id="555555"),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"name": "organizations/555555/locations/global/intelligenceConfig"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_organization_intelligence_config"

    @pytest.mark.asyncio
    async def test_update_organization_intelligence_config(self, oauth_credentials):
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSUpdateOrganizationIntelligenceConfig(
                    organization_id="555555",
                    intelligence_config_json='{"editionConfig":"TRIAL"}',
                    update_mask="editionConfig",
                ),
                credentials=oauth_credentials,
            )
        )
        mock_client = create_mock_client(200, {"editionConfig": "TRIAL"})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_organization_intelligence_config"


# ============================================================================
# Error handling
# ============================================================================


class TestGCSErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetBucketConfig(bucket="missing"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Not Found"}})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = GoogleCloudStorageNodeConfig(
            config=GCSGetServiceAccountConfig(project_id="proj-1"), credentials=None
        )
        node = GoogleCloudStorageNode(
            node_id="test-gcs-node",
            node_type="automation-google-cloud-storage",
            node_data={},
            config=config,
            sio=Mock(),
            sid="test-sid",
            workflow_id="test-workflow",
            user_id="test-user",
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_json_metadata(self, oauth_credentials):
        config = GoogleCloudStorageNodeConfig(
            config=GCSUpdateBucketConfig(bucket="bucket-a", metadata_json="not-json"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        with pytest.raises(ValueError, match="must be valid JSON"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_freshen_service_account_is_passthrough(self):
        credential = {
            "credential_type": "google_cloud_storage_service_account",
            "service_account_json": '{"type":"service_account","client_email":"svc@example.com","private_key":"k","private_key_id":"kid","token_uri":"https://oauth2.googleapis.com/token"}',
        }
        result = await GoogleCloudStorageNode.freshen_credential(credential)
        assert result == credential

    @pytest.mark.asyncio
    async def test_service_account_token_exchange(self, service_account_credentials):
        request_spy = {}
        mock_response = create_mock_response(200, {"access_token": "sa-token"})
        mock_client = Mock()
        node = GoogleCloudStorageNode(
            node_id="test-gcs-node",
            node_type="automation-google-cloud-storage",
            node_data={},
            config=None,
            sio=Mock(),
            sid="test-sid",
            workflow_id="test-workflow",
            user_id="test-user",
        )

        async def async_post(*args, **kwargs):
            request_spy["url"] = kwargs.get("url") or (args[0] if args else None)
            request_spy["data"] = kwargs.get("data")
            return mock_response

        mock_client.post = async_post

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit

        with patch("nodes.google_cloud_storage_node.jwt.encode", return_value="signed-jwt"), patch(
            PATCH_TARGET, return_value=mock_client
        ):
            token = await node._ensure_fresh_token(service_account_credentials)

        assert token == "sa-token"
        assert request_spy["url"] == "https://oauth2.googleapis.com/token"
        assert request_spy["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
        assert request_spy["data"]["assertion"] == "signed-jwt"


# ============================================================================
# Dynamic options
# ============================================================================


class TestGCSDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_bucket_options(self):
        with patch("nodes.google_cloud_storage_node._gcs_request",
            return_value={
                "status": "success",
                "data": {
                    "items": [{"name": "bucket-a"}, {"name": "bucket-b"}],
                    "nextPageToken": "next-1",
                },
            },
        ):
            result = await GoogleCloudStorageNode.load_field_options(
                "bucket",
                {"access_token": "mock_access_token"},
                context={"project_id": "proj-1"},
                page_token="page-1",
                search="buck",
            )
        assert "options" in result
        assert result["options"][0]["value"] == "bucket-a"
        assert result["options"][1]["label"] == "bucket-b"
        assert result["next_page_token"] == "next-1"

    @pytest.mark.asyncio
    async def test_load_bucket_options_no_project(self):
        result = await GoogleCloudStorageNode.load_field_options(
            "bucket", {"access_token": "mock_access_token"}, context={}
        )
        assert result["options"] == []

    @pytest.mark.asyncio
    async def test_load_bucket_options_from_service_account(self, service_account_credentials):
        gcs_request = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "items": [{"name": "bucket-a"}],
                },
            }
        )
        mint_token = AsyncMock(return_value="sa-token")
        with patch("nodes.google_cloud_storage_node._mint_service_account_access_token", mint_token), patch(
            "nodes.google_cloud_storage_node._gcs_request", gcs_request
        ):
            result = await GoogleCloudStorageNode.load_field_options(
                "bucket",
                service_account_credentials.model_dump(),
                context={},
            )

        assert result["options"] == [{"label": "bucket-a", "value": "bucket-a"}]
        mint_token.assert_awaited_once()
        _, kwargs = gcs_request.await_args
        assert kwargs["params"]["project"] == "proj-1"

    @pytest.mark.asyncio
    async def test_load_folder_options(self):
        gcs_request = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "items": [{"name": "reports/"}, {"name": "exports/"}],
                    "nextPageToken": "next-folders",
                },
            }
        )
        with patch("nodes.google_cloud_storage_node._gcs_request", gcs_request):
            result = await GoogleCloudStorageNode.load_field_options(
                "folder_name",
                {"access_token": "mock_access_token"},
                context={"bucket": "bucket-a"},
                page_token="page-1",
                search="rep",
            )

        assert result["options"] == [
            {"label": "reports/", "value": "reports/"},
            {"label": "exports/", "value": "exports/"},
        ]
        assert result["next_page_token"] == "next-folders"
        _, kwargs = gcs_request.await_args
        assert kwargs["params"]["prefix"] == "rep"

    @pytest.mark.asyncio
    async def test_load_managed_folder_options(self):
        gcs_request = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "managedFolders": [{"name": "tenant-a/"}, {"name": "tenant-b/"}],
                },
            }
        )
        with patch("nodes.google_cloud_storage_node._gcs_request", gcs_request):
            result = await GoogleCloudStorageNode.load_field_options(
                "managed_folder",
                {"access_token": "mock_access_token"},
                context={"bucket": "bucket-a"},
            )

        assert result["options"] == [
            {"label": "tenant-a/", "value": "tenant-a/"},
            {"label": "tenant-b/", "value": "tenant-b/"},
        ]

    @pytest.mark.asyncio
    async def test_load_folder_options_without_bucket(self):
        result = await GoogleCloudStorageNode.load_field_options(
            "folder_name", {"access_token": "mock_access_token"}, context={}
        )
        assert result["options"] == []


# ============================================================================
# Trigger (poll-based: on_new_object)
# ============================================================================


class TestGCSTriggerResolvePayload:
    def test_resolve_returns_none_for_poll_op(self):
        """The cron webhook is a wake-up signal — execute() must run the poll."""
        resolved = GoogleCloudStorageNode.resolve_trigger_payload(
            {"some": "payload"}, {"operation": "on_new_object"}
        )
        assert resolved is None

    def test_resolve_passthrough_for_normal_op(self):
        """Non-trigger ops pass the payload through unchanged."""
        payload = {"some": "payload"}
        resolved = GoogleCloudStorageNode.resolve_trigger_payload(
            payload, {"operation": "list_objects"}
        )
        assert resolved is payload


def _bind_gcs_state(node, initial=None):
    """Back the node's dedup with an in-memory node-state store (the cursor now
    lives in workflow_node_state, not config). Returns the store dict."""
    store = dict(initial or {})

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(store))
        if new_state is not None:
            store.clear()
            store.update(new_state)
        return result

    node._update_node_state = _update
    return store


class TestGCSTriggerPollMock:
    @pytest.mark.asyncio
    async def test_first_poll_baselines_emits_nothing(self, oauth_credentials):
        """First poll (no cursor) records the baseline cursor and emits nothing,
        so we don't fire on the bucket's entire existing contents."""
        config = GoogleCloudStorageNodeConfig(
            config=GCSOnNewObjectConfig(bucket="bucket-a", prefix="incoming/"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = _bind_gcs_state(node)
        mock_client = create_mock_client(
            200,
            {
                "items": [
                    {"name": "incoming/a.txt", "timeCreated": "2026-06-19T10:00:00Z"},
                    {"name": "incoming/b.txt", "timeCreated": "2026-06-19T11:00:00Z"},
                ]
            },
        )
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_new_object"
        assert result["new_count"] == 0
        assert result["items"] == []
        # Cursor advanced to the newest existing object's creation time AND
        # persisted to node state (not config).
        assert result["last_polled_at"] == "2026-06-19T11:00:00Z"
        assert store == {"last_polled_at": "2026-06-19T11:00:00Z"}

    @pytest.mark.asyncio
    async def test_second_poll_emits_only_new_and_dedupes(self, oauth_credentials):
        """With a cursor in node state, only objects created after it are
        emitted; objects at or before the cursor are deduped out."""
        config = GoogleCloudStorageNodeConfig(
            config=GCSOnNewObjectConfig(bucket="bucket-a", prefix="incoming/"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = _bind_gcs_state(node, {"last_polled_at": "2026-06-19T11:00:00Z"})
        mock_client = create_mock_client(
            200,
            {
                "items": [
                    # Already seen (== cursor) — must be deduped.
                    {"name": "incoming/b.txt", "timeCreated": "2026-06-19T11:00:00Z"},
                    # New since the cursor — must be emitted.
                    {"name": "incoming/c.txt", "timeCreated": "2026-06-19T12:00:00Z"},
                    {"name": "incoming/d.txt", "timeCreated": "2026-06-19T13:00:00Z"},
                ]
            },
        )
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 2
        emitted_names = {o["name"] for o in result["items"]}
        assert emitted_names == {"incoming/c.txt", "incoming/d.txt"}
        # Cursor advances to the newest emitted object, persisted to node state.
        assert result["last_polled_at"] == "2026-06-19T13:00:00Z"
        assert store == {"last_polled_at": "2026-06-19T13:00:00Z"}

    @pytest.mark.asyncio
    async def test_poll_no_new_objects_returns_empty(self, oauth_credentials):
        """When nothing is newer than the cursor, new_count is 0 (downstream is
        skipped via trigger_produced_no_event)."""
        config = GoogleCloudStorageNodeConfig(
            config=GCSOnNewObjectConfig(bucket="bucket-a"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        _bind_gcs_state(node, {"last_polled_at": "2026-06-19T13:00:00Z"})
        mock_client = create_mock_client(
            200,
            {
                "items": [
                    {"name": "old.txt", "timeCreated": "2026-06-19T12:00:00Z"},
                ]
            },
        )
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_api_error_propagates(self, oauth_credentials):
        """An API error on the list call is returned, not swallowed."""
        config = GoogleCloudStorageNodeConfig(
            config=GCSOnNewObjectConfig(bucket="missing"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Not Found"}})
        with patch(PATCH_TARGET, return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_trigger_produced_no_event_false_for_new_items(self, oauth_credentials):
        """When the poll emitted items, downstream must NOT be skipped."""
        node = create_node(
            GoogleCloudStorageNodeConfig(
                config=GCSOnNewObjectConfig(bucket="bucket-a"),
                credentials=oauth_credentials,
            )
        )
        assert (
            node.trigger_produced_no_event(
                {"operation": "on_new_object", "new_count": 2, "items": [{}, {}]}
            )
            is False
        )
